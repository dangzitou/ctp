package com.ctp.dashboard;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.sql.Timestamp;
import java.time.LocalDate;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Core tick processing service:
 * - Stores latest tick in Redis (hash: instrument -> tick JSON)
 * - Persists tick to MySQL
 * - Broadcasts via WebSocket
 */
@Service
public class TickService {

    private static final Logger log = LoggerFactory.getLogger(TickService.class);

    private static final String REDIS_KEY_ALL = "ctp:all_instruments";
    private static final String REDIS_KEY_PREFIX = "ctp:tick:";
    private static final String REDIS_KEY_KLINE_PREFIX = "ctp:kline:";

    private final RedisTemplate<String, Object> redisTemplate;
    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final TickWebSocketHandler webSocketHandler;

    // Latest tick cache
    private final Map<String, Tick> tickCache = new ConcurrentHashMap<>();
    private final Map<String, List<KlineCandle>> klineCache = new ConcurrentHashMap<>();

    // Counters
    private final AtomicLong tickCount = new AtomicLong(0);

    public TickService(RedisTemplate<String, Object> redisTemplate,
                       JdbcTemplate jdbcTemplate,
                       ObjectMapper objectMapper,
                       TickWebSocketHandler webSocketHandler) {
        this.redisTemplate = redisTemplate;
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
        this.webSocketHandler = webSocketHandler;
    }

    public void processTick(Tick tick) {
        if (tick == null || tick.getInstrumentId() == null) return;

        long count = tickCount.incrementAndGet();

        // 1. Update in-memory cache
        tickCache.put(tick.getInstrumentId(), tick);

        // 2. Store in Redis
        try {
            String tickJson = objectMapper.writeValueAsString(tick);
            redisTemplate.opsForHash().put(REDIS_KEY_PREFIX + tick.getInstrumentId(), "data", tickJson);
            redisTemplate.opsForHash().put(REDIS_KEY_PREFIX + tick.getInstrumentId(), "price", String.valueOf(tick.getPrice()));
            redisTemplate.opsForHash().put(REDIS_KEY_PREFIX + tick.getInstrumentId(), "updateTime", tick.getUpdateTime());
            // Add to all instruments set
            redisTemplate.opsForSet().add(REDIS_KEY_ALL, tick.getInstrumentId());
            // Set expiry (24h)
            redisTemplate.expire(REDIS_KEY_PREFIX + tick.getInstrumentId(), java.time.Duration.ofHours(24));
        } catch (Exception e) {
            log.warn("Redis write failed for {}: {}", tick.getInstrumentId(), e.getMessage());
        }

        // 3. Update K-line candle
        updateKline(tick);

        // 4. Broadcast via WebSocket (async)
        webSocketHandler.broadcast(tick);

        // 5. Persist to MySQL (batch every 100 ticks)
        if (count % 100 == 0) {
            persistTickBatch();
        }
    }

    private void updateKline(Tick tick) {
        String iid = tick.getInstrumentId();
        long ts = tick.getTimestamp();
        // Align to 1-minute candle
        long candleTs = (ts / 60) * 60;

        klineCache.computeIfAbsent(iid, k -> new ArrayList<>());

        List<KlineCandle> candles = klineCache.get(iid);
        synchronized (candles) {
            if (candles.isEmpty() || candles.get(candles.size() - 1).openTime < candleTs) {
                // New candle
                candles.add(new KlineCandle(candleTs, tick.getPrice(), tick.getPrice(),
                        tick.getPrice(), tick.getPrice(), tick.getVolume()));
            } else {
                // Update current candle
                KlineCandle c = candles.get(candles.size() - 1);
                c.highPrice = Math.max(c.highPrice, tick.getPrice());
                c.lowPrice = Math.min(c.lowPrice, tick.getPrice());
                c.closePrice = tick.getPrice();
                c.volume += tick.getVolume();
            }
            // Keep only last 500 candles
            while (candles.size() > 500) {
                candles.remove(0);
            }
        }

        // Store in Redis
        try {
            String key = REDIS_KEY_KLINE_PREFIX + iid + ":1min";
            String candleJson = objectMapper.writeValueAsString(candles);
            redisTemplate.opsForValue().set(key, candleJson);
        } catch (Exception e) {
            log.warn("Redis kline write failed: {}", e.getMessage());
        }
    }

    public List<Tick> getAllInstruments() {
        return new ArrayList<>(tickCache.values());
    }

    public Tick getTick(String instrumentId) {
        return tickCache.get(instrumentId);
    }

    public List<KlineCandle> getKline(String instrumentId) {
        List<KlineCandle> candles = klineCache.get(instrumentId);
        return candles != null ? candles : Collections.emptyList();
    }

    private void persistTickBatch() {
        // Batch insert recent ticks to MySQL (async)
        try {
            List<Tick> batch = new ArrayList<>(tickCache.values());
            if (batch.isEmpty()) return;

            String sql = """
                INSERT INTO ticks (instrument_id, last_price, bid_price, ask_price, volume, open_interest, update_time, trading_day)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE last_price=VALUES(last_price), bid_price=VALUES(bid_price),
                ask_price=VALUES(ask_price), volume=VALUES(volume), open_interest=VALUES(open_interest),
                update_time=VALUES(update_time)
                """;

            for (Tick t : batch) {
                jdbcTemplate.update(sql,
                    t.getInstrumentId(), t.getPrice(), t.getBid(), t.getAsk(),
                    t.getVolume(), t.getOpenInterest(),
                    Timestamp.valueOf(t.getUpdateTime() != null ? t.getUpdateTime() : "1970-01-01 00:00:00"),
                    LocalDate.now().toString()
                );
            }
            log.debug("Persisted {} ticks to MySQL", batch.size());
        } catch (Exception e) {
            log.warn("MySQL persist failed: {}", e.getMessage());
        }
    }

    /** 1-minute K-line candle */
    public static class KlineCandle {
        public long openTime;
        public double openPrice;
        public double highPrice;
        public double lowPrice;
        public double closePrice;
        public long volume;

        public KlineCandle() {}
        public KlineCandle(long openTime, double open, double high, double low, double close, long volume) {
            this.openTime = openTime;
            this.openPrice = open;
            this.highPrice = high;
            this.lowPrice = low;
            this.closePrice = close;
            this.volume = volume;
        }
    }
}
