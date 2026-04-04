package com.ctp.market;

import java.io.*;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

/**
 * Java TCP client that connects to md_server.py (port 19842)
 * and receives real-time tick data for all 279 futures contracts.
 *
 * This works WITHOUT needing the official CTP JAR.
 * Just run md_server.py first, then this Java client.
 *
 * Usage:
 *   1. Start md_server: python md_server.py 19842
 *   2. Run this class
 */
public class MdServerClient {

    private static final String MD_SERVER_HOST = "127.0.0.1";
    private static final int MD_SERVER_PORT = 19842;

    // In-memory store for latest tick of each instrument
    private final Map<String, TickData> tickMap = new ConcurrentHashMap<>();

    // Thread-safe instrument list
    private final Set<String> instruments = ConcurrentHashMap.newKeySet();

    // Countdown latch for orderly shutdown
    private final CountDownLatch connectedLatch = new CountDownLatch(1);
    private volatile boolean running = false;

    public static void main(String[] args) throws Exception {
        MdServerClient client = new MdServerClient();

        // Parse optional instrument filter from args
        String filter = args.length > 0 ? args[0] : null;

        // Register shutdown hook
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            System.out.println("\n[Java] Shutting down...");
            client.stop();
        }));

        client.start(filter);
    }

    public void start(String instrumentFilter) throws Exception {
        running = true;
        System.out.println("==========================================");
        System.out.println("  CTP Market Data Client (Java TCP)");
        System.out.println("==========================================");
        System.out.println("  Connecting to: " + MD_SERVER_HOST + ":" + MD_SERVER_PORT);
        System.out.println("  Filter: " + (instrumentFilter != null ? instrumentFilter : "ALL"));
        System.out.println("==========================================\n");

        // Connect in background thread
        Thread readerThread = new Thread(() -> {
            try {
                connectAndRead(instrumentFilter);
            } catch (Exception e) {
                if (running) {
                    System.err.println("[Java] Connection error: " + e.getMessage());
                    e.printStackTrace();
                }
            }
        }, "MdServerReader");
        readerThread.start();

        // Wait for connection
        connectedLatch.await(10, TimeUnit.SECONDS);

        if (!running) return;

        // Print stats every 10 seconds
        Thread statsThread = new Thread(() -> {
            while (running) {
                try {
                    Thread.sleep(10000);
                    printStats();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    break;
                }
            }
        }, "StatsPrinter");
        statsThread.start();

        // Keep alive
        Thread.sleep(Long.MAX_VALUE);
    }

    public void stop() {
        running = false;
    }

    private void connectAndRead(String filter) throws IOException {
        try (Socket socket = new Socket()) {
            socket.setKeepAlive(true);
            socket.setSoTimeout(0); // blocking read
            socket.connect(new java.net.InetSocketAddress(MD_SERVER_HOST, MD_SERVER_PORT), 5000);

            System.out.println("[Java] Connected to md_server");
            System.out.println("[Java] Receiving tick data...\n");
            connectedLatch.countDown();

            BufferedReader reader = new BufferedReader(
                new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8));

            String line;
            while (running && (line = reader.readLine()) != null) {
                if (line.startsWith("TICK:")) {
                    String json = line.substring(5);
                    processTick(json, filter);
                } else if (line.startsWith("LOGIN_OK:")) {
                    System.out.println("[md_server] " + line);
                } else if (line.startsWith("SUBSCRIBED:")) {
                    System.out.println("[md_server] " + line);
                } else if (line.startsWith("LOGIN_FAILED:")) {
                    System.err.println("[md_server] " + line);
                }
            }
        }
    }

    private void processTick(String json, String filter) {
        try {
            TickData tick = TickData.fromJson(json);

            // Apply filter if specified
            if (filter != null && !tick.instrumentId.contains(filter)) {
                return;
            }

            tickMap.put(tick.instrumentId, tick);
            instruments.add(tick.instrumentId);

            // Print tick to console
            System.out.printf("[%s.%03d] %-10s | Last: %-10.5f | Vol: %-10d | Bid: %-10.5f | Ask: %-10.5f%n",
                tick.updateTime != null ? tick.updateTime : "00:00:00",
                tick.updateMillisec,
                tick.instrumentId,
                tick.lastPrice,
                tick.volume,
                tick.bidPrice1,
                tick.askPrice1);

        } catch (Exception e) {
            // Silently ignore parse errors for non-tick JSON
        }
    }

    private void printStats() {
        System.out.println("\n--- Stats: " + instruments.size() + " instruments, " + tickMap.size() + " with data ---");
        List<String> sorted = new ArrayList<>(instruments);
        Collections.sort(sorted);
        for (String iid : sorted) {
            TickData t = tickMap.get(iid);
            if (t != null && t.lastPrice > 0) {
                System.out.printf("  %-10s %-10.5f  (Bid: %-10.5f  Ask: %-10.5f)%n",
                    iid, t.lastPrice, t.bidPrice1, t.askPrice1);
            }
        }
        System.out.println();
    }

    // ==================== Tick Data Model ====================

    static class TickData {
        String instrumentId;
        double lastPrice;
        int volume;
        double bidPrice1;
        double askPrice1;
        double openInterest;
        double change;
        double changePct;
        long timestamp;
        String updateTime;
        int updateMillisec;

        static TickData fromJson(String json) {
            TickData t = new TickData();
            // Simple JSON parser (no external deps)
            t.instrumentId = parseString(json, "instrument_id");
            t.lastPrice = parseDouble(json, "price");
            t.volume = parseInt(json, "volume");
            t.bidPrice1 = parseDouble(json, "bid");
            t.askPrice1 = parseDouble(json, "ask");
            t.openInterest = parseDouble(json, "open_interest");
            t.change = parseDouble(json, "change");
            t.changePct = parseDouble(json, "change_pct");
            t.timestamp = parseLong(json, "timestamp");
            t.updateTime = parseString(json, "update_time");
            t.updateMillisec = (int)(t.timestamp % 1000);
            return t;
        }

        private static String parseString(String json, String key) {
            String k = "\"" + key + "\"";
            int ki = json.indexOf(k);
            if (ki < 0) return "";
            int colon = json.indexOf(':', ki);
            int start = json.indexOf('"', colon + 1);
            int end = json.indexOf('"', start + 1);
            return start >= 0 && end > start ? json.substring(start + 1, end) : "";
        }

        private static double parseDouble(String json, String key) {
            String k = "\"" + key + "\"";
            int ki = json.indexOf(k);
            if (ki < 0) return 0;
            int colon = json.indexOf(':', ki);
            int comma = json.indexOf(',', colon);
            int end = comma > 0 ? comma : json.indexOf('}', colon);
            String val = json.substring(colon + 1, end).trim();
            try { return Double.parseDouble(val); } catch (Exception e) { return 0; }
        }

        private static int parseInt(String json, String key) {
            return (int) parseDouble(json, key);
        }

        private static long parseLong(String json, String key) {
            return (long) parseDouble(json, key);
        }
    }
}
