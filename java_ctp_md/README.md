# Java CTP Market Data Client

This module now defaults to a pure Java TCP client that connects to `runtime/md_simnow/md_server.py`.
It does not require the official CTP Java JAR for the default build.

## Architecture

```text
SimNow CTP
  -> runtime/md_simnow/md_server.py
  -> TCP JSON on 127.0.0.1:19842
  -> java_ctp_md client jar
```

## Run

1. Start the Python market data server:

```bash
cd E:\Develop\projects\ctp
python runtime\md_simnow\md_server.py 19842
```

2. Build the Java client:

```bash
cd E:\Develop\projects\ctp\java_ctp_md
mvn package
```

3. Run the packaged jar:

```bash
java -jar target\ctp-market-data-1.0.0-jar-with-dependencies.jar
```

You can also run the lightweight prebuilt jar:

```bash
java -jar target\MdServerClient.jar
```

## Filter

Pass a substring to filter instruments:

```bash
java -jar target\ctp-market-data-1.0.0-jar-with-dependencies.jar cu
```

## Optional Direct CTP Mode

If you place the official CTP Java API jar at:

```text
src/main/resources/thostmduserapi.jar
```

then Maven will automatically activate the `direct-ctp` profile and switch the main class to `MarketDataClient`.
