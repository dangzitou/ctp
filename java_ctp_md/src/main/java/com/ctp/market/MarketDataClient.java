package com.ctp.market;

import thostmduserapi.*;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Properties;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * SimNow CTP Market Data Client
 *
 * Connects to SimNow CTP market data front and subscribes to specified instruments.
 * Prints tick data (LastPrice, Volume, BidPrice1, AskPrice1, UpdateTime) to console.
 */
public class MarketDataClient extends CThostFtdcMdSpi {

    private static final Logger logger = LoggerFactory.getLogger(MarketDataClient.class);

    private final CThostFtdcMdApi mdApi;
    private final String frontAddress;
    private final String brokerId;
    private final String userId;
    private final String password;
    private final String[] instruments;
    private final CountDownLatch latch;

    private boolean connected = false;
    private boolean loggedIn = false;

    /**
     * Constructor - initializes the CTP MD API
     *
     * @param frontAddress Market data front address (e.g., tcp://182.254.243.31:40011)
     * @param brokerId     Broker ID
     * @param userId       User ID
     * @param password     Password
     * @param instruments  Array of instrument IDs to subscribe
     */
    public MarketDataClient(String frontAddress, String brokerId, String userId,
                            String password, String[] instruments) {
        this.frontAddress = frontAddress;
        this.brokerId = brokerId;
        this.userId = userId;
        this.password = password;
        this.instruments = instruments;
        this.latch = new CountDownLatch(1);

        // Create Market Data API
        // Passing empty string uses default flow path for storing temporary data
        this.mdApi = CThostFtdcMdApi.CreateFtdcMdApi("");

        logger.info("MarketDataClient created for front: {}", frontAddress);
    }

    /**
     * Start the market data client
     */
    public void start() {
        if (mdApi == null) {
            logger.error("Failed to create MD API");
            return;
        }

        // Register SPI callback implementation
        mdApi.RegisterSpi(this);

        // Register front address
        mdApi.RegisterFront(frontAddress);

        // Initialize the API, which starts the connection thread
        logger.info("Initializing MD API, connecting to front: {}", frontAddress);
        mdApi.Init();

        // Wait for connection and login to complete
        try {
            // Wait up to 30 seconds for login
            boolean success = latch.await(30, TimeUnit.SECONDS);
            if (!success) {
                logger.error("Timeout waiting for login, exiting...");
            }
        } catch (InterruptedException e) {
            logger.error("Interrupted while waiting: {}", e.getMessage());
            Thread.currentThread().interrupt();
        }
    }

    /**
     * Stop the market data client
     */
    public void stop() {
        logger.info("Stopping MarketDataClient...");
        if (mdApi != null) {
            mdApi.Release();
        }
    }

    // ==================== SPI Callbacks ====================

    /**
     * Called when connection to front is established
     */
    @Override
    public void OnFrontConnected() {
        logger.info("Connected to SimNow");
        connected = true;

        // Automatically request login after connection
        reqUserLogin();
    }

    /**
     * Called when connection to front is lost
     */
    @Override
    public void OnFrontDisconnected(int nReason) {
        logger.warn("Disconnected from SimNow, reason: {}", nReason);
        connected = false;
        loggedIn = false;
    }

    /**
     * Called when login request completes
     */
    @Override
    public void OnRspUserLogin(CThostFtdcRspUserLoginField pRspUserLogin,
                               CThostFtdcRspInfoField pRspInfo, int nRequestID, boolean bIsLast) {
        if (pRspInfo != null && pRspInfo.getErrorID() == 0) {
            loggedIn = true;
            String tradingDay = pRspUserLogin != null ? pRspUserLogin.getTradingDay() : "N/A";
            logger.info("Login OK, TradingDay={}", tradingDay);

            // Subscribe to instruments after successful login
            subscribeInstruments();

            // Release latch to allow main thread to continue
            latch.countDown();
        } else {
            String errorMsg = pRspInfo != null ? pRspInfo.getErrorMsg() : "Unknown error";
            int errorId = pRspInfo != null ? pRspInfo.getErrorID() : -1;
            logger.error("Login failed, ErrorID={}, ErrorMsg={}", errorId, errorMsg);
        }
    }

    /**
     * Called when login request fails (response error)
     */
    @Override
    public void OnRspUserLoginError(CThostFtdcRspInfoField pRspInfo, int nRequestID, boolean bIsLast) {
        if (pRspInfo != null) {
            logger.error("Login error response, ErrorID={}, ErrorMsg={}",
                    pRspInfo.getErrorID(), pRspInfo.getErrorMsg());
        }
    }

    /**
     * Called when logout request completes
     */
    @Override
    public void OnRspUserLogout(CThostFtdcUserLogoutField pUserLogout,
                                CThostFtdcRspInfoField pRspInfo, int nRequestID, boolean bIsLast) {
        if (pUserLogout != null) {
            logger.info("User logout, UserID={}", pUserLogout.getUserID());
        }
        loggedIn = false;
    }

    /**
     * Called when subscription request completes
     */
    @Override
    public void OnRspSubMarketData(CThostFtdcSpecificInstrumentField pSpecificInstrument,
                                    CThostFtdcRspInfoField pRspInfo, int nRequestID, boolean bIsLast) {
        if (pSpecificInstrument != null) {
            if (pRspInfo != null && pRspInfo.getErrorID() == 0) {
                logger.debug("Subscribed to: {}", pSpecificInstrument.getInstrumentID());
            } else if (pRspInfo != null) {
                logger.warn("Failed to subscribe to {}: {}",
                        pSpecificInstrument.getInstrumentID(), pRspInfo.getErrorMsg());
            }
        }
    }

    /**
     * Called when unsubscription request completes
     */
    @Override
    public void OnRspUnSubMarketData(CThostFtdcSpecificInstrumentField pSpecificInstrument,
                                     CThostFtdcRspInfoField pRspInfo, int nRequestID, boolean bIsLast) {
        if (pSpecificInstrument != null) {
            logger.debug("Unsubscribed from: {}", pSpecificInstrument.getInstrumentID());
        }
    }

    /**
     * Called when depth market data is received (tick data)
     */
    @Override
    public void OnRtnDepthMarketData(CThostFtdcDepthMarketDataField pDepthMarketData) {
        if (pDepthMarketData == null) {
            return;
        }

        String instrumentId = pDepthMarketData.getInstrumentID();
        double lastPrice = pDepthMarketData.getLastPrice();
        int volume = pDepthMarketData.getVolume();
        double bidPrice1 = pDepthMarketData.getBidPrice1();
        double askPrice1 = pDepthMarketData.getAskPrice1();
        String updateTime = pDepthMarketData.getUpdateTime();
        int updateMillisec = pDepthMarketData.getUpdateMillisec();

        // Format output: InstrumentID, LastPrice, Volume, BidPrice1, AskPrice1, UpdateTime
        StringBuilder sb = new StringBuilder();
        sb.append(String.format("[%s.%03d] %s | Last: %s | Vol: %d | Bid: %s | Ask: %s",
                updateTime != null ? updateTime : "00:00:00",
                updateMillisec,
                instrumentId != null ? instrumentId : "N/A",
                formatPrice(lastPrice),
                volume,
                formatPrice(bidPrice1),
                formatPrice(askPrice1)));

        // Add additional fields if available
        double openInterest = pDepthMarketData.getOpenInterest();
        if (openInterest > 0) {
            sb.append(String.format(" | OI: %.0f", openInterest));
        }

        int bidVolume1 = pDepthMarketData.getBidVolume1();
        int askVolume1 = pDepthMarketData.getAskVolume1();
        if (bidVolume1 > 0 || askVolume1 > 0) {
            sb.append(String.format(" | BidVol: %d | AskVol: %d", bidVolume1, askVolume1));
        }

        logger.info(sb.toString());
    }

    /**
     * Called when error response is received
     */
    @Override
    public void OnRspError(CThostFtdcRspInfoField pRspInfo, int nRequestID, boolean bIsLast) {
        if (pRspInfo != null) {
            logger.error("RspError, ErrorID={}, ErrorMsg={}",
                    pRspInfo.getErrorID(), pRspInfo.getErrorMsg());
        }
    }

    // ==================== Helper Methods ====================

    /**
     * Request user login
     */
    private void reqUserLogin() {
        CThostFtdcReqUserLoginField loginField = new CThostFtdcReqUserLoginField();
        loginField.setBrokerID(brokerId);
        loginField.setUserID(userId);
        loginField.setPassword(password);

        int result = mdApi.ReqUserLogin(loginField, 0);
        if (result == 0) {
            logger.info("Login request sent, BrokerID={}, UserID={}", brokerId, userId);
        } else {
            logger.error("Failed to send login request, error code: {}", result);
        }
    }

    /**
     * Subscribe to market data for all instruments
     */
    private void subscribeInstruments() {
        if (instruments == null || instruments.length == 0) {
            logger.warn("No instruments to subscribe");
            return;
        }

        logger.info("Subscribing to {} instruments...", instruments.length);

        // CTP Java API expects char[][] not String[]
        char[][] charCodes = new char[instruments.length][];
        for (int i = 0; i < instruments.length; i++) {
            charCodes[i] = instruments[i].toCharArray();
        }

        int result = mdApi.SubscribeMarketData(charCodes);
        if (result == 0) {
            logger.info("Subscribe request sent for {} instruments", instruments.length);
        } else {
            logger.error("Failed to subscribe, error code: {}", result);
        }
    }

    /**
     * Format price value for display
     */
    private String formatPrice(double price) {
        if (price == 0 || price == Double.MAX_VALUE) {
            return "N/A";
        }
        return String.format("%.5f", price);
    }

    // ==================== Main Method ====================

    public static void main(String[] args) {
        // Load configuration
        String frontAddress = "tcp://182.254.243.31:40011";
        String brokerId = "9999";
        String userId = "9999";
        String password = "9999";
        String instrumentList = "cu2605,al2605,zn2605,ma2605,cf2605,if2606,sc2605";

        // Allow override via system properties or environment
        frontAddress = System.getProperty("ctp.front.address", frontAddress);
        brokerId = System.getProperty("ctp.broker.id", brokerId);
        userId = System.getProperty("ctp.user.id", userId);
        password = System.getProperty("ctp.password", password);
        instrumentList = System.getProperty("ctp.instrument.list", instrumentList);

        // Parse instruments
        String[] instruments = instrumentList.split(",");

        logger.info("=== CTP Market Data Client Starting ===");
        logger.info("Front: {}", frontAddress);
        logger.info("Broker: {}", brokerId);
        logger.info("User: {}", userId);
        logger.info("Instruments: {}", instrumentList);

        // Create and start client
        MarketDataClient client = new MarketDataClient(
                frontAddress, brokerId, userId, password, instruments);

        // Add shutdown hook
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            logger.info("Shutdown hook triggered");
            client.stop();
        }));

        // Start the client (blocks until login completes or timeout)
        client.start();

        // Keep running for a while to receive tick data
        if (client.isLoggedIn()) {
            logger.info("=== Receiving tick data, press Ctrl+C to exit ===");
            try {
                // Keep main thread alive to receive callbacks
                // In production, this would be replaced with proper lifecycle management
                Thread.sleep(Long.MAX_VALUE);
            } catch (InterruptedException e) {
                logger.info("Main thread interrupted");
                Thread.currentThread().interrupt();
            }
        } else {
            logger.error("Failed to login, exiting...");
        }

        client.stop();
        logger.info("=== CTP Market Data Client Stopped ===");
    }

    /**
     * Check if login was successful
     */
    public boolean isLoggedIn() {
        return loggedIn;
    }

    /**
     * Check if connected to front
     */
    public boolean isConnected() {
        return connected;
    }
}
