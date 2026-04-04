package com.ctp.dashboard;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {

    private final TickWebSocketHandler tickWebSocketHandler;

    public WebSocketConfig(TickWebSocketHandler tickWebSocketHandler) {
        this.tickWebSocketHandler = tickWebSocketHandler;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(tickWebSocketHandler, "/ws/ticks")
                .setAllowedOrigins("*");
    }
}
