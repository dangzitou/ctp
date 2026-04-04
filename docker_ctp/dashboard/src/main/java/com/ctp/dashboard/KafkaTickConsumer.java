package com.ctp.dashboard;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

/**
 * Kafka consumer - receives raw tick data from 'ctp-ticks' topic,
 * processes it and stores in Redis + MySQL.
 */
@Component
public class KafkaTickConsumer {

    private static final Logger log = LoggerFactory.getLogger(KafkaTickConsumer.class);

    private final TickService tickService;
    private final ObjectMapper objectMapper;

    public KafkaTickConsumer(TickService tickService, ObjectMapper objectMapper) {
        this.tickService = tickService;
        this.objectMapper = objectMapper;
    }

    @KafkaListener(topics = "${kafka.topic:ctp-ticks}", groupId = "${kafka.group-id:dashboard-consumer}")
    public void consume(String message) {
        try {
            Tick tick = objectMapper.readValue(message, Tick.class);
            tickService.processTick(tick);
        } catch (Exception e) {
            log.error("Failed to process tick: {}", e.getMessage());
        }
    }
}
