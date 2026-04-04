import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, r"E:\Develop\projects\ctp\runtime\md_simnow")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import thostmduserapi as mdapi
from runtime.front_config import resolve_ctp_connection

DEFAULT_FRONT = "tcp://182.254.243.31:40011"
DEFAULT_SYMBOLS = ["cu2605", "al2605", "ma2605", "ta2605", "cf2605", "if2606"]

class MdClient(mdapi.CThostFtdcMdSpi):
    def __init__(self, settings, symbols):
        super().__init__()
        self.settings = settings
        self.symbols = [s.encode("utf-8") for s in symbols]
        self.api = None

    def run(self):
        self.api = mdapi.CThostFtdcMdApi.CreateFtdcMdApi()
        self.api.RegisterFront(self.settings.front)
        self.api.RegisterSpi(self)
        self.api.Init()

    def OnFrontConnected(self):
        print("OnFrontConnected", flush=True)
        auth_fn = getattr(self.api, "ReqAuthenticate", None)
        if self.settings.requires_auth and callable(auth_fn):
            req = mdapi.CThostFtdcReqAuthenticateField()
            req.BrokerID = self.settings.broker_id
            req.UserID = self.settings.user_id
            req.AppID = self.settings.app_id
            req.AuthCode = self.settings.auth_code
            req.UserProductInfo = self.settings.user_product_info
            auth_fn(req, 0)
            print("Authenticate request sent", flush=True)
            return
        req = mdapi.CThostFtdcReqUserLoginField()
        req.BrokerID = self.settings.broker_id
        req.UserID = self.settings.user_id
        req.Password = self.settings.password
        self.api.ReqUserLogin(req, 0)

    def OnRspAuthenticate(self, pRspAuthenticateField, pRspInfo, nRequestID, bIsLast):
        if pRspInfo is not None and pRspInfo.ErrorID != 0:
            print(f"Authenticate failed: {pRspInfo.ErrorID} {pRspInfo.ErrorMsg}", flush=True)
            return
        print("Authenticate succeed", flush=True)
        req = mdapi.CThostFtdcReqUserLoginField()
        req.BrokerID = self.settings.broker_id
        req.UserID = self.settings.user_id
        req.Password = self.settings.password
        self.api.ReqUserLogin(req, 1)

    def OnFrontDisconnected(self, nReason):
        print(f"OnFrontDisconnected nReason={nReason}", flush=True)

    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID, bIsLast):
        if pRspInfo is not None and pRspInfo.ErrorID != 0:
            print(f"Login failed: {pRspInfo.ErrorID} {pRspInfo.ErrorMsg}", flush=True)
            return
        print(f"Login succeed. TradingDay={pRspUserLogin.TradingDay}", flush=True)
        self.api.SubscribeMarketData(self.symbols, len(self.symbols))

    def OnRspSubMarketData(self, pSpecificInstrument, pRspInfo, nRequestID, bIsLast):
        if pRspInfo is not None and pRspInfo.ErrorID != 0:
            print(
                f"Subscribe failed: {pSpecificInstrument.InstrumentID} "
                f"{pRspInfo.ErrorID} {pRspInfo.ErrorMsg}",
                flush=True,
            )
            return
        print(f"Subscribe succeed: {pSpecificInstrument.InstrumentID}", flush=True)

    def OnRtnDepthMarketData(self, pDepthMarketData):
        print(
            "TICK "
            f"{pDepthMarketData.InstrumentID} "
            f"last={pDepthMarketData.LastPrice} "
            f"vol={pDepthMarketData.Volume} "
            f"bid1={pDepthMarketData.BidPrice1} "
            f"ask1={pDepthMarketData.AskPrice1} "
            f"time={pDepthMarketData.UpdateTime}",
            flush=True,
        )


def parse_args():
    settings = resolve_ctp_connection(DEFAULT_FRONT)
    parser = argparse.ArgumentParser(description="CTP market data demo")
    parser.add_argument("--front", default=settings.front)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--seconds", type=int, default=300)
    return parser.parse_args()


def main():
    args = parse_args()
    settings = resolve_ctp_connection(DEFAULT_FRONT)
    settings.front = args.front
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        raise SystemExit("no symbols provided")

    print(f"API version: {mdapi.CThostFtdcMdApi.GetApiVersion()}", flush=True)
    print(f"Front: {settings.front} ({settings.front_source})", flush=True)
    print(f"Auth source: {settings.auth_source}", flush=True)
    if settings.redis_error:
        print(f"Redis config warning: {settings.redis_error}", flush=True)
    print(f"Symbols: {', '.join(symbols)}", flush=True)

    client = MdClient(settings, symbols)
    client.run()
    time.sleep(args.seconds)


if __name__ == "__main__":
    sys.exit(main())
