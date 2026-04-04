package com.ctp.dashboard;

import java.io.Serializable;

/** Tick data model - received from Kafka and stored in Redis */
public class Tick implements Serializable {
    private static final long serialVersionUID = 1L;

    private String type;
    private String instrumentId;
    private String exchange;
    private double price;
    private int volume;
    private double bid;
    private double ask;
    private int bidVolume;
    private int askVolume;
    private long openInterest;
    private double change;
    private double changePct;
    private double openPrice;
    private double highPrice;
    private double lowPrice;
    private long timestamp;
    private String updateTime;
    private String tradingDay;

    public Tick() {}

    public Tick(String type, String instrumentId, String exchange, double price, int volume,
                double bid, double ask, int bidVolume, int askVolume, long openInterest,
                double change, double changePct, double openPrice, double highPrice, double lowPrice,
                long timestamp, String updateTime, String tradingDay) {
        this.type = type;
        this.instrumentId = instrumentId;
        this.exchange = exchange;
        this.price = price;
        this.volume = volume;
        this.bid = bid;
        this.ask = ask;
        this.bidVolume = bidVolume;
        this.askVolume = askVolume;
        this.openInterest = openInterest;
        this.change = change;
        this.changePct = changePct;
        this.openPrice = openPrice;
        this.highPrice = highPrice;
        this.lowPrice = lowPrice;
        this.timestamp = timestamp;
        this.updateTime = updateTime;
        this.tradingDay = tradingDay;
    }

    // Getters
    public String getType() { return type; }
    public String getInstrumentId() { return instrumentId; }
    public String getExchange() { return exchange; }
    public double getPrice() { return price; }
    public int getVolume() { return volume; }
    public double getBid() { return bid; }
    public double getAsk() { return ask; }
    public int getBidVolume() { return bidVolume; }
    public int getAskVolume() { return askVolume; }
    public long getOpenInterest() { return openInterest; }
    public double getChange() { return change; }
    public double getChangePct() { return changePct; }
    public double getOpenPrice() { return openPrice; }
    public double getHighPrice() { return highPrice; }
    public double getLowPrice() { return lowPrice; }
    public long getTimestamp() { return timestamp; }
    public String getUpdateTime() { return updateTime; }
    public String getTradingDay() { return tradingDay; }

    // Setters
    public void setType(String type) { this.type = type; }
    public void setInstrumentId(String instrumentId) { this.instrumentId = instrumentId; }
    public void setExchange(String exchange) { this.exchange = exchange; }
    public void setPrice(double price) { this.price = price; }
    public void setVolume(int volume) { this.volume = volume; }
    public void setBid(double bid) { this.bid = bid; }
    public void setAsk(double ask) { this.ask = ask; }
    public void setBidVolume(int bidVolume) { this.bidVolume = bidVolume; }
    public void setAskVolume(int askVolume) { this.askVolume = askVolume; }
    public void setOpenInterest(long openInterest) { this.openInterest = openInterest; }
    public void setChange(double change) { this.change = change; }
    public void setChangePct(double changePct) { this.changePct = changePct; }
    public void setOpenPrice(double openPrice) { this.openPrice = openPrice; }
    public void setHighPrice(double highPrice) { this.highPrice = highPrice; }
    public void setLowPrice(double lowPrice) { this.lowPrice = lowPrice; }
    public void setTimestamp(long timestamp) { this.timestamp = timestamp; }
    public void setUpdateTime(String updateTime) { this.updateTime = updateTime; }
    public void setTradingDay(String tradingDay) { this.tradingDay = tradingDay; }

    /** Exchange prefix mapping */
    public static String getExchange(String instrumentId) {
        if (instrumentId == null) return "UNKNOWN";
        String suffix = instrumentId.replaceAll("[0-9]", "").toLowerCase();
        return switch (suffix) {
            case "cu", "al", "zn", "pb", "ni", "sn", "ss", "au", "ag", "ru", "bu", "rb", "hc", "i", "j", "jm" -> "SHFE";
            case "m", "y", "c", "cs", "p", "a", "b", "l", "pp", "v", "eb", "eg", "pg" -> "DCE";
            case "ma", "ta", "fg", "pf", "rm", "sr", "cf", "cy", "oi", "wh", "pm" -> "CZCE";
            case "if", "ih", "ic", "im", "tf", "ts", "t" -> "CFFEX";
            case "sc", "bc" -> "INE";
            default -> "UNKNOWN";
        };
    }
}
