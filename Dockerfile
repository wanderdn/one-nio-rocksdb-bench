FROM maven:3.9.9-eclipse-temurin-21
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends python3 strace && rm -rf /var/lib/apt/lists/*
WORKDIR /project
COPY pom.xml .
RUN mvn -q dependency:go-offline
COPY src src
RUN mvn -q -DskipTests package
ENTRYPOINT ["java","-Xms128m","-Xmx128m","-XX:+UseSerialGC","--add-opens=java.base/java.lang=ALL-UNNAMED","--add-opens=java.base/java.nio=ALL-UNNAMED","--add-exports=java.base/jdk.internal.ref=ALL-UNNAMED","-jar","/project/target/one-nio-rocksdb-bench-1.0.jar"]
