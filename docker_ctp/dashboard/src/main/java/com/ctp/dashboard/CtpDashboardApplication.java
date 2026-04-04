package com.ctp.dashboard;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class CtpDashboardApplication {
    public static void main(String[] args) {
        SpringApplication.run(CtpDashboardApplication.class, args);
    }
}
