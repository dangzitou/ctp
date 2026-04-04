package com.ctp.dashboard;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.*;

/**
 * REST API endpoints:
 * GET /api/instruments - all instruments with latest prices
 * GET /api/tick/{instrumentId} - latest tick for one instrument
 * GET /api/kline/{instrumentId} - K-line data
 */
@RestController
@RequestMapping("/api")
public class ApiController {

    private final TickService tickService;
    private final RedisTemplate<String, Object> redisTemplate;
    private final ObjectMapper objectMapper;

    public ApiController(TickService tickService, RedisTemplate<String, Object> redisTemplate, ObjectMapper objectMapper) {
        this.tickService = tickService;
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
    }

    /** All instruments with latest prices */
    @GetMapping("/instruments")
    public List<Map<String, Object>> getInstruments() {
        return tickService.getAllInstruments().stream().map(tick -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("instrument_id", tick.getInstrumentId());
            m.put("exchange", tick.getExchange());
            m.put("name", tick.getInstrumentId());
            m.put("last_price", tick.getPrice());
            m.put("change", tick.getChange());
            m.put("change_pct", tick.getChangePct());
            m.put("volume", tick.getVolume());
            m.put("open_interest", tick.getOpenInterest());
            m.put("bid_price1", tick.getBid());
            m.put("ask_price1", tick.getAsk());
            m.put("update_time", tick.getUpdateTime());
            return m;
        }).toList();
    }

    /** Latest tick for one instrument */
    @GetMapping("/tick/{instrumentId}")
    public Map<String, Object> getTick(@PathVariable String instrumentId) {
        Tick tick = tickService.getTick(instrumentId);
        if (tick == null) {
            return Map.of("error", "not found", "instrument_id", instrumentId);
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("instrument_id", tick.getInstrumentId());
        m.put("exchange", tick.getExchange());
        m.put("price", tick.getPrice());
        m.put("bid", tick.getBid());
        m.put("ask", tick.getAsk());
        m.put("volume", tick.getVolume());
        m.put("open_interest", tick.getOpenInterest());
        m.put("change", tick.getChange());
        m.put("change_pct", tick.getChangePct());
        m.put("timestamp", tick.getTimestamp());
        m.put("update_time", tick.getUpdateTime());
        return m;
    }

    /** K-line data for an instrument */
    @GetMapping("/kline/{instrumentId}")
    public List<Map<String, Object>> getKline(@PathVariable String instrumentId) {
        return tickService.getKline(instrumentId).stream().map(c -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("timestamp", c.openTime * 1000); // ms for JS
            m.put("open", c.openPrice);
            m.put("high", c.highPrice);
            m.put("low", c.lowPrice);
            m.put("close", c.closePrice);
            m.put("volume", c.volume);
            return m;
        }).toList();
    }

    /** Redis stats */
    @GetMapping("/stats")
    public Map<String, Object> getStats() {
        Map<String, Object> stats = new LinkedHashMap<>();
        stats.put("instruments", tickService.getAllInstruments().size());
        stats.put("websocket_clients", 0); // filled by controller
        return stats;
    }
}
