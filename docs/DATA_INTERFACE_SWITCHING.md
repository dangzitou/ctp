# Data Interface Switching

This repository now supports decoupling market-data front addresses from account credentials.

The runtime resolution order is:

1. `CTP_FRONT` or `CTP_FRONTS`
2. Redis set `ctp_collect_url`
3. built-in default front

Authentication resolution order is:

1. `CTP_BROKER_ID`, `CTP_USER_ID`, `CTP_PASSWORD`, `CTP_APP_ID`, `CTP_AUTH_CODE`, `CTP_USER_PRODUCT_INFO`
2. Redis hash `ctp_collect_auth`
3. built-in defaults

This lets you switch company lines without editing code.

## Redis Keys

Front set:

- key: `ctp_collect_url`
- type: `SET`
- example members:
  - `tcp://101.230.178.179:53313`
  - `tcp://101.230.178.178:53313`

Auth hash:

- key: `ctp_collect_auth`
- type: `HASH`
- supported fields:
  - `broker_id`
  - `user_id`
  - `password`
  - `app_id`
  - `auth_code`
  - `user_product_info`

## Example Commands

Add front addresses:

```bash
redis-cli SADD ctp_collect_url tcp://101.230.178.179:53313
redis-cli SADD ctp_collect_url tcp://101.230.178.178:53313
redis-cli SMEMBERS ctp_collect_url
```

Set company credentials:

```bash
redis-cli HSET ctp_collect_auth broker_id your_broker_id
redis-cli HSET ctp_collect_auth user_id your_user_id
redis-cli HSET ctp_collect_auth password 'your_password'
redis-cli HSET ctp_collect_auth app_id your_app_id
redis-cli HSET ctp_collect_auth auth_code 'your_auth_code'
redis-cli HSET ctp_collect_auth user_product_info 'company-md'
redis-cli HGETALL ctp_collect_auth
```

Clear old entries:

```bash
redis-cli DEL ctp_collect_url
redis-cli DEL ctp_collect_auth
```

## Runtime Behavior

- If multiple fronts exist in `ctp_collect_url`, the default selection mode is sorted-first.
- You can override selection with:
  - `CTP_FRONT_PICK=random`
  - `CTP_FRONT_INDEX=1`
- The selected front is locked for the current process lifetime.
- To switch to another line, update Redis and restart the relevant process or container.

## Supported Entry Points

These components now resolve fronts and credentials through the shared runtime config:

- `runtime/md_simnow/md_server.py`
- `runtime/md_simnow/live_md_demo.py`
- `runtime/md_simnow/scan_contracts.py`
- `runtime/dashboard/ctp_bridge.py`
- `docker_ctp/seed/ctp_seed.py`
- `java_ctp_md/src/main/java/com/ctp/market/MarketDataClient.java`

## Enterprise Authentication Decoupling

Some company fronts require more than `broker_id`, `user_id`, and `password`.

This repo keeps those concerns separate:

- transport line selection lives in `ctp_collect_url`
- account and app authentication live in `ctp_collect_auth`

That means you can:

- keep the same account and switch lines
- keep the same line and rotate account credentials
- test a new company front without rewriting application code

## Operational Recommendation

For production-like operation:

1. write the current company lines into `ctp_collect_url`
2. write the current account/auth settings into `ctp_collect_auth`
3. restart the Windows relay or `ctp_seed.py`
4. verify logs show the chosen front and auth source
5. verify fresh ticks appear in Kafka, Redis, and dashboard APIs

## Notes

- Secrets should not be committed into the repository.
- Prefer Redis or environment variables for credentials.
- Some CTP Python bindings do not expose full authenticate callbacks consistently across all builds. This repo attempts authentication when the API method is available and otherwise falls back to normal login.
