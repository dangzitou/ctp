import argparse
import sys
import time

sys.path.insert(0, r"E:\Develop\projects\ctp\runtime\md_simnow")
import thostmduserapi as mdapi

DEFAULT_FRONT = "tcp://182.254.243.31:40011"
DEFAULT_SYMBOLS = ["cu2605", "al2605", "ma2605", "ta2605", "cf2605", "if2606"]

class MdClient(mdapi.CThostFtdcMdSpi):
    def __init__(self, front: str, symbols):
        super().__init__()
        self.front = front
        self.symbols = [s.encode("utf-8") for s in symbols]
        self.api = None

    def run(self):
        self.api = mdapi.CThostFtdcMdApi.CreateFtdcMdApi()
        self.api.RegisterFront(self.front)
        self.api.RegisterSpi(self)
        self.api.Init()

    def OnFrontConnected(self):
        print("OnFrontConnected", flush=True)
        req = mdapi.CThostFtdcReqUserLoginField()
        self.api.ReqUserLogin(req, 0)

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
    parser = argparse.ArgumentParser(description="CTP market data demo")
    parser.add_argument("--front", default=DEFAULT_FRONT)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--seconds", type=int, default=300)
    return parser.parse_args()


def main():
    args = parse_args()
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        raise SystemExit("no symbols provided")

    print(f"API version: {mdapi.CThostFtdcMdApi.GetApiVersion()}", flush=True)
    print(f"Front: {args.front}", flush=True)
    print(f"Symbols: {', '.join(symbols)}", flush=True)

    client = MdClient(args.front, symbols)
    client.run()
    time.sleep(args.seconds)


if __name__ == "__main__":
    sys.exit(main())
