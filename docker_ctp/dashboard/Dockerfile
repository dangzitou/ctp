FROM alpine:3.19 AS builder

RUN apk add --no-cache openjdk17 maven

WORKDIR /app

COPY pom.xml .
COPY src ./src

RUN mvn dependency:go-offline -B && \
    mvn package -DskipTests -B

FROM alpine:3.19

RUN apk add --no-cache openjdk17-jre

WORKDIR /app

COPY --from=builder /app/target/*.jar app.jar

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "app.jar"]
