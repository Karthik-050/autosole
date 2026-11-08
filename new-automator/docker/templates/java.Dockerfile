# syntax=docker/dockerfile:1
{% if language == 'java-gradle' %}
FROM gradle:8-jdk{{ java_version }} AS builder
WORKDIR /app
COPY build.gradle* settings.gradle* gradle* ./
COPY src ./src
RUN gradle build -x test --no-daemon

FROM eclipse-temurin:{{ java_version }}-jre-jammy AS runner
WORKDIR /app
ENV PORT={{ port }}
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/build/libs/*.jar app.jar
RUN useradd -m -u 1000 javauser && chown -R javauser:javauser /app
USER javauser
EXPOSE {{ port }}
HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -f http://localhost:{{ port }}{{ health_check_path }} || exit 1
CMD ["java", "-jar", "app.jar"]

{% else %}
FROM maven:3.9-eclipse-temurin-{{ java_version }} AS builder
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline -B
COPY src ./src
RUN mvn package -DskipTests -B

FROM eclipse-temurin:{{ java_version }}-jre-jammy AS runner
WORKDIR /app
ENV PORT={{ port }}
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /app/target/*.jar app.jar
RUN useradd -m -u 1000 javauser && chown -R javauser:javauser /app
USER javauser
EXPOSE {{ port }}
HEALTHCHECK --interval=20s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -f http://localhost:{{ port }}{{ health_check_path }} || exit 1
CMD ["java", "-jar", "app.jar"]
{% endif %}
