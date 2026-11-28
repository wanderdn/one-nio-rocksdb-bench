package bench;

import one.nio.mem.SharedMemoryLongMap;
import one.nio.os.Mem;
import org.HdrHistogram.Histogram;
import org.rocksdb.*;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.io.RandomAccessFile;
import java.lang.management.ManagementFactory;

/** Single client, identical JSON bytes and seeded key trace for every engine. */
public final class Bench {
    static final long GIB = 1L << 30;
    static final long SEED = 0x5eed1234L;
    static volatile long blackhole;
    static final char[] ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_".toCharArray();

    static String token(long id, int device) {
        SplittableRandom r = new SplittableRandom(id * 31 + device + SEED);
        StringBuilder s = new StringBuilder(163);
        for (int i = 0; i < 163; i++) s.append(i == 22 ? ':' : ALPHABET[r.nextInt(64)]);
        return s.toString();
    }
    static byte[] payload(long id) {
        StringBuilder s = new StringBuilder(800);
        s.append("{\"subscription_id\":\"").append(String.format(Locale.ROOT, "%016x", id)).append("\",\"devices\":[");
        for (int d = 0; d < (id % 20 == 0 ? 2 : 1); d++) {
            if (d != 0) s.append(',');
            s.append("{\"fcm_token\":\"").append(token(id,d)).append("\",\"device_id\":\"")
             .append(String.format(Locale.ROOT,"%016x", id * 2 + d))
             .append("\",\"platform\":\"android\",\"model\":\"Pixel 9\",\"os_version\":\"16\",\"app_version\":\"8.4.1\",\"locale\":\"ru-RU\",\"updated_at\":1767225600}");
        }
        return s.append("]}").toString().getBytes(StandardCharsets.UTF_8);
    }
    // Multiples of 20 preserve exactly 95/5 distribution. Target is logical key+JSON bytes.
    static long countFor(long target) {
        long group = 0;
        for (int i=0;i<20;i++) group += 8 + payload(i).length;
        return Math.max(20, ((target + group - 1) / group) * 20);
    }
    static byte[] key(long id) { return ByteBuffer.allocate(8).putLong(id).array(); }
    static int capacity(long count) { return Math.toIntExact(count * 2 + 1); }
    static long nioFileSize(long count) { return (long)(count * (payload(1).length + 100) * 1.5) + capacity(count) * 8L + (1L<<20); }

    /** Immutable benchmark: disable TTL checks and access-time writes to mmap pages. */
    static final class ReadOnlyLongMap extends SharedMemoryLongMap<byte[]> {
        ReadOnlyLongMap(int capacity,String file,long size) throws Exception { super(capacity,file,size); }
        @Override protected boolean isExpired(long entry, boolean touch) { return false; }
        void sync() { if(Mem.msync(mmap.getAddr(),mmap.getSize(),Mem.MS_SYNC)!=0)throw new IllegalStateException("msync failed"); }
        void randomAdvice() { if(Mem.posix_madvise(mmap.getAddr(),mmap.getSize(),Mem.POSIX_MADV_RANDOM)!=0)throw new IllegalStateException("madvise failed"); }
        // Every value is a primitive byte[]: no per-record serializer references exist.
        @Override protected void storeSchema() {
            if(serializer!=null) { setHeader(UID_OFFSET,serializer.uid());setHeader(CUSTOM_SIZE_OFFSET,0); }
        }
    }
    static final class Nio implements AutoCloseable {
        final SharedMemoryLongMap<byte[]> map;
        Nio(Path dir, long count) throws Exception {
            map = new ReadOnlyLongMap(capacity(count), dir.resolve("one-nio.map").toString(), nioFileSize(count));
            map.setSerializer(byte[].class);
            map.setTimeToLive(Long.MAX_VALUE);
            ((ReadOnlyLongMap)map).randomAdvice();
        }
        public void close() { map.close(); }
    }
    static final class Rocks implements AutoCloseable {
        static { RocksDB.loadLibrary(); }
        final LRUCache blocks, rows;
        final BloomFilter bloom;
        final Options options;
        final RocksDB db;
        final Statistics statistics;
        final ReadOptions reads = new ReadOptions().setVerifyChecksums(true);
        Rocks(Path dir, boolean create, String profile, int blockSize) throws Exception {
            RocksDB.loadLibrary();
            boolean mmap = profile.startsWith("mmap");
            boolean row = profile.startsWith("row");
            boolean noCache = profile.startsWith("nocache");
            reads.setFillCache(!noCache);
            reads.setAsyncIo(profile.endsWith("-async"));
            long cacheBytes=Long.parseLong(System.getenv().getOrDefault("BENCH_CACHE_BYTES",Long.toString(GIB)));
            if(cacheBytes<(64L<<20))throw new IllegalArgumentException("cache must be >=64 MiB");
            blocks = new LRUCache(row ? cacheBytes - (32L<<20) : cacheBytes, 4, true, 0.2);
            rows = new LRUCache(32L<<20, 4, true, 0.0);
            bloom = new BloomFilter(10, false);
            BlockBasedTableConfig table = new BlockBasedTableConfig().setBlockSize(blockSize)
                .setBlockCache(blocks).setNoBlockCache(mmap || noCache).setCacheIndexAndFilterBlocks(!noCache)
                .setPinTopLevelIndexAndFilter(!noCache).setFilterPolicy(bloom)
                .setDataBlockIndexType(DataBlockIndexType.kDataBlockBinaryAndHash)
                .setDataBlockHashTableUtilRatio(0.75).setBlockRestartInterval(1);
            options = new Options().setCreateIfMissing(create).setTableFormatConfig(table)
                .setCompressionType(CompressionType.NO_COMPRESSION).setBottommostCompressionType(CompressionType.NO_COMPRESSION)
                .setWriteBufferSize(32L<<20).setMaxWriteBufferNumber(2).setMaxBackgroundJobs(4)
                .setAllowMmapReads(mmap).setUseDirectReads(!mmap).setUseDirectIoForFlushAndCompaction(!mmap)
                .setMaxOpenFiles(-1).setAdviseRandomOnOpen(true);
            statistics = "1".equals(System.getenv("BENCH_STATS")) ? new Statistics() : null;
            if(statistics!=null)options.setStatistics(statistics);
            if (row) options.setRowCache(rows);
            if(!create)options.setDisableAutoCompactions(true);
            db = create || profile.contains("-rw") ? RocksDB.open(options, dir.resolve("rocks").toString()) : RocksDB.openReadOnly(options, dir.resolve("rocks").toString());
            System.out.println("CONFIG profile="+profile+" directReads="+!mmap+" noBlockCache="+noCache+" rowCache="+row+" fillCache="+!noCache);
        }
        void stats(String phase) {
            System.out.printf(Locale.ROOT,"CACHE %s blockBytes=%d rowBytes=%d%n",phase,blocks.getUsage(),rows.getUsage());
            if(statistics!=null)System.out.println("TICKERS "+phase+" "+statistics.toString().replace('\n',';'));
        }
        public void close() { db.close(); reads.close(); options.close(); if(statistics!=null)statistics.close(); bloom.close(); rows.close(); blocks.close(); }
    }
    static void prepare(Path dir, long bytes, int blockSize) throws Exception {
        Files.createDirectories(dir);
        if (Files.exists(dir.resolve("manifest.properties"))) throw new IllegalStateException("Dataset already exists; use a new directory");
        long count = countFor(bytes), logical=0;
        try (Nio n = new Nio(dir,count); Rocks r = new Rocks(dir,true,"block",blockSize);
             WriteOptions wo = new WriteOptions().setDisableWAL(true); WriteBatch batch = new WriteBatch()) {
            for (long i=0;i<count;i++) {
                byte[] value = payload(i);
                logical += value.length + 8;
                if(!n.map.put(i,value)) throw new AssertionError("one-nio put failed at "+i);
                batch.put(key(i),value);
                if (i%4096==4095) { r.db.write(wo,batch); batch.clear(); }
                if (i%1_000_000==0) System.out.println("LOAD " + i + "/" + count);
            }
            if(batch.count()>0) r.db.write(wo,batch);
            try (FlushOptions f = new FlushOptions().setWaitForFlush(true)) { r.db.flush(f); }
            r.db.compactRange();
            if (n.map.getCount()!=count) throw new AssertionError("one-nio count");
        }
        String manifest = "count="+count+"\nlogicalBytes="+logical+"\nblockSize="+blockSize+"\nseed="+SEED+"\n";
        Files.writeString(dir.resolve("manifest.properties"),manifest);
        System.out.println("PREPARED " + manifest.replace('\n',' '));
        System.out.println("PAYLOAD " + new String(payload(20),StandardCharsets.UTF_8));
    }
    static Properties manifest(Path dir) throws Exception {
        Properties p = new Properties(); try(var in=Files.newInputStream(dir.resolve("manifest.properties"))) { p.load(in); } return p;
    }
    // Evict ONLY benchmark files, avoiding global drop_caches and inherited memcg charges.
    static void evict(Path dir) throws Exception {
        try(var files=Files.walk(dir)) {
            for(Path p:files.filter(Files::isRegularFile).toList()) {
                try(RandomAccessFile f=new RandomAccessFile(p.toFile(),"rw")) {
                    f.getFD().sync();
                    int rc=Mem.posix_fadvise(f.getFD(),0,0,Mem.POSIX_FADV_DONTNEED);
                    if(rc!=0)throw new IllegalStateException("fadvise failed: "+p+" rc="+rc);
                }
            }
        }
    }
    static final class Trace {
        final long[] ids;
        final Long[] boxed;
        final ArrayList<byte[]> keys;
        final SplittableRandom random;
        Trace(long count,int size) {
            this(count,size,SEED);
        }
        Trace(long count,int size,long seed) {
            random=new SplittableRandom(seed);
            ids=new long[size]; boxed=new Long[size]; keys=new ArrayList<>(size);
            HashSet<Long> seen=new HashSet<>();
            for(int i=0;i<size;i++) { long id; do{id=random.nextLong(count);}while(!seen.add(id)); ids[i]=id;boxed[i]=id;keys.add(key(id)); }
        }
        void shuffle() {
            for(int i=ids.length-1;i>0;i--) {
                int j=random.nextInt(i+1);
                long id=ids[i];ids[i]=ids[j];ids[j]=id;
                Long b=boxed[i];boxed[i]=boxed[j];boxed[j]=b;
                byte[] k=keys.get(i);keys.set(i,keys.get(j));keys.set(j,k);
            }
        }
        void renew(long count) {
            for(int i=0;i<ids.length;i++) { long id=random.nextLong(count);ids[i]=id;boxed[i]=id;ByteBuffer.wrap(keys.get(i)).putLong(id); }
        }
    }
    static long consume(byte[] value) {
        if(value==null) throw new AssertionError("Missing key");
        long h=1; for(byte b:value) h=h*31+(b&255); return h;
    }
    static String stat(String file) {
        try{return Files.readString(Path.of("/sys/fs/cgroup/"+file));}catch(Exception e){return "unavailable";}
    }
    static void snapshot(String phase) throws Exception {
        System.out.println("STAT " + phase + " memory.current=" + stat("memory.current").trim());
        for(String f:List.of("memory.stat","memory.events","io.stat","cpu.stat","cpu.max","cpuset.cpus.effective")) System.out.println("STAT "+phase+" "+f+" "+stat(f).replace('\n',';'));
        for(String f:List.of("status","io","schedstat"))System.out.println("PROC "+phase+" "+f+" "+Files.readString(Path.of("/proc/self/"+f)).replace('\n',';'));
    }
    static long gcCount() { return ManagementFactory.getGarbageCollectorMXBeans().stream().mapToLong(x->Math.max(0,x.getCollectionCount())).sum(); }
    static long gcMillis() { return ManagementFactory.getGarbageCollectorMXBeans().stream().mapToLong(x->Math.max(0,x.getCollectionTime())).sum(); }
    static void run(Path dir, String engine, String mode, String profile, int passes, int warmup) throws Exception {
        Properties m=manifest(dir); long count=Long.parseLong(m.getProperty("count"));
        int size=(int)Math.min(5000,count);
        evict(dir);
        Nio n=engine.equals("nio") ? new Nio(dir,count) : null;
        Rocks r=n==null ? new Rocks(dir,false,profile,Integer.parseInt(m.getProperty("blockSize"))) : null;
        int threads=Integer.parseInt(System.getenv().getOrDefault("BENCH_THREADS","1"));
        int multiSize=Integer.parseInt(System.getenv().getOrDefault("BENCH_MULTI_SIZE","5000"));
        ExecutorService workers=threads>1?Executors.newFixedThreadPool(threads):null;
        Histogram[] requestHist=new Histogram[threads];
        for(int w=0;w<threads;w++)requestHist[w]=new Histogram(3);
        System.out.println("CONCURRENCY threads="+threads+" multiKeysPerRequest="+multiSize);
        try {
            if(n!=null)((ReadOnlyLongMap)n.map).sync();
            String gate=System.getenv("BENCH_GATE");
            if(gate!=null) {
                System.out.println("READY_FOR_MEMORY_LIMIT");
                while(!Files.exists(Path.of(gate)))Thread.sleep(100);
            }
            Trace check=new Trace(count,size);
            for(int i=0;i<size;i++) {
                byte[] v=n!=null?n.map.get(check.boxed[i]):r.db.get(r.reads,check.keys.get(i));
                if(!Arrays.equals(v,payload(check.ids[i]))) throw new AssertionError("Incorrect payload "+check.ids[i]+" got="+(v==null?"null":new String(v,StandardCharsets.UTF_8))+" expected="+new String(payload(check.ids[i]),StandardCharsets.UTF_8));
            }
            long checksum=0; Histogram hist=new Histogram(3); Histogram individual=new Histogram(3);
            var os=(com.sun.management.OperatingSystemMXBean)ManagementFactory.getOperatingSystemMXBean();
            for(int phase=0;phase<2;phase++) {
                hist.reset(); individual.reset(); for(Histogram h:requestHist)h.reset();
                checksum=0;
                // Uniform warmup and measurement must never replay the same prefix.
                Trace trace=new Trace(count,size,mode.equals("uniform") && phase==0?SEED^0x12345678abcdefL:SEED);
                int rounds=phase==0?warmup:passes;
                snapshot(phase==0?"warmup-start":"measure-start");
                if(r!=null)r.stats(phase==0?"warmup-start":"measure-start");
                long cpuStart=os.getProcessCpuTime(), gcStart=gcCount(), gcTimeStart=gcMillis();
                long start=System.nanoTime();
                for(int pass=0;pass<rounds;pass++) {
                    long t=System.nanoTime();
                    if(mode.equals("uniform"))trace.renew(count);else trace.shuffle();
                    if(workers!=null) {
                        ArrayList<Callable<Long>> tasks=new ArrayList<>();
                        final int passIndex=pass;
                        for(int w=0;w<threads;w++) {
                            final int worker=w;
                            tasks.add(()-> {
                                long sum=0;
                                if(engine.equals("multi")) {
                                    for(int first=worker*multiSize;first<size;first+=threads*multiSize) {
                                        long begin=System.nanoTime();
                                        List<byte[]> values=r.db.multiGetAsList(r.reads,trace.keys.subList(first,Math.min(size,first+multiSize)));
                                        for(byte[] value:values)sum+=consume(value);
                                        requestHist[worker].recordValue(System.nanoTime()-begin);
                                    }
                                } else {
                                    for(int i=worker*size/threads;i<(worker+1)*size/threads;i++) {
                                        boolean sample=(((long)passIndex*size+i)&15)==0;
                                        long begin=sample?System.nanoTime():0;
                                        sum+=consume(n!=null?n.map.get(trace.boxed[i]):r.db.get(r.reads,trace.keys.get(i)));
                                        if(sample)requestHist[worker].recordValue(System.nanoTime()-begin);
                                    }
                                }
                                return sum;
                            });
                        }
                        for(Future<Long> future:workers.invokeAll(tasks))checksum+=future.get();
                    } else if(engine.equals("multi")) {
                        List<byte[]> values=r.db.multiGetAsList(r.reads,trace.keys);
                        for(byte[] v:values)checksum+=consume(v);
                    } else {
                        for(int i=0;i<size;i++) {
                            boolean sample=(((long)pass*size+i)&(mode.equals("uniform")?15:1023))==0;
                            long sampleStart=sample?System.nanoTime():0;
                            checksum+=consume(n!=null?n.map.get(trace.boxed[i]):r.db.get(r.reads,trace.keys.get(i)));
                            if(sample)individual.recordValue(System.nanoTime()-sampleStart);
                        }
                    }
                    hist.recordValue(System.nanoTime()-t);
                    if(pass%25==24) {
                        double seconds=(System.nanoTime()-start)/1e9;
                        System.out.printf(Locale.ROOT,"PROGRESS %s phase=%d passes=%d/%d gets=%d seconds=%.3f getsPerSecond=%.1f%n",engine,phase,pass+1,rounds,(long)(pass+1)*size,seconds,(long)(pass+1)*size/seconds);
                    }
                }
                long elapsed=System.nanoTime()-start;
                long cpuElapsed=os.getProcessCpuTime()-cpuStart;
                if(phase==1) {
                    blackhole=checksum;
                    if(workers!=null)for(Histogram h:requestHist)individual.add(h);
                    System.out.printf(Locale.ROOT,"REQUEST_METRICS threads=%d maxKeysPerRequest=%d samples=%d p50Us=%.3f p95Us=%.3f p99Us=%.3f p999Us=%.3f maxUs=%.3f%n",threads,engine.equals("multi")?multiSize:1,individual.getTotalCount(),individual.getValueAtPercentile(50)/1e3,individual.getValueAtPercentile(95)/1e3,individual.getValueAtPercentile(99)/1e3,individual.getValueAtPercentile(99.9)/1e3,individual.getMaxValue()/1e3);
                    System.out.printf(Locale.ROOT,"RESULT {\"engine\":\"%s\",\"mode\":\"%s\",\"profile\":\"%s\",\"passes\":%d,\"keysPerPass\":%d,\"gets\":%d,\"seconds\":%.6f,\"getsPerSecond\":%.3f,\"nsPerGet\":%.3f,\"batchP50Ms\":%.6f,\"batchP95Ms\":%.6f,\"batchP99Ms\":%.6f,\"checksum\":%d}%n",engine,mode,profile,passes,size,(long)passes*size,elapsed/1e9,(long)passes*size/(elapsed/1e9),elapsed/(double)((long)passes*size),hist.getValueAtPercentile(50)/1e6,hist.getValueAtPercentile(95)/1e6,hist.getValueAtPercentile(99)/1e6,checksum);
                    System.out.printf(Locale.ROOT,"METRICS {\"cpuSeconds\":%.6f,\"cpuPctOneCore\":%.3f,\"cpuNsPerGet\":%.3f,\"gcCount\":%d,\"gcMillis\":%d,\"batchP90Ms\":%.6f,\"batchP999Ms\":%.6f,\"batchMinMs\":%.6f,\"batchMaxMs\":%.6f,\"batchMeanMs\":%.6f,\"batchStdDevMs\":%.6f,\"getSamples\":%d,\"getP50Ns\":%d,\"getP90Ns\":%d,\"getP95Ns\":%d,\"getP99Ns\":%d,\"getP999Ns\":%d,\"getMaxNs\":%d}%n",cpuElapsed/1e9,100.0*cpuElapsed/elapsed,cpuElapsed/(double)((long)passes*size),gcCount()-gcStart,gcMillis()-gcTimeStart,hist.getValueAtPercentile(90)/1e6,hist.getValueAtPercentile(99.9)/1e6,hist.getMinValue()/1e6,hist.getMaxValue()/1e6,hist.getMean()/1e6,hist.getStdDeviation()/1e6,individual.getTotalCount(),individual.getValueAtPercentile(50),individual.getValueAtPercentile(90),individual.getValueAtPercentile(95),individual.getValueAtPercentile(99),individual.getValueAtPercentile(99.9),individual.getMaxValue());
                    snapshot("measure-end");
                    if(r!=null)r.stats("measure-end");
                    if(r!=null) { System.out.println("ROCKS "+r.db.getProperty("rocksdb.stats")); }
                }
            }
        } finally { if(workers!=null)workers.shutdownNow();if(n!=null)n.close();if(r!=null)r.close(); }
    }
    static void selftest(Path dir) throws Exception {
        if(payload(0).length<=payload(1).length)throw new AssertionError("device distribution");
        int two=0;for(int i=0;i<100;i++)if(new String(payload(i),StandardCharsets.UTF_8).contains("},{"))two++;
        if(two!=5)throw new AssertionError("95/5");
        prepare(dir,8L<<20,4096);
        for(String e:List.of("nio","get","multi"))run(dir,e,"hot","row",3,1);
        System.out.println("SELFTEST OK");
    }
    public static void main(String[] args) throws Exception {
        Path dir=Path.of(args[1]);
        switch(args[0]) {
            case "prepare" -> prepare(dir, args.length>2?Long.parseLong(args[2]):4*GIB,args.length>3?Integer.parseInt(args[3]):4096);
            case "run" -> run(dir,args[2],args[3],args[4],Integer.parseInt(args[5]),args.length>6?Integer.parseInt(args[6]):2000);
            case "selftest" -> selftest(dir);
            default -> throw new IllegalArgumentException("prepare DIR [BYTES BLOCKSIZE] | run DIR nio|get|multi hot|uniform row|block|mmap PASSES [WARMUP] | selftest DIR");
        }
    }
}
