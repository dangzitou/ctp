"""用 TTS 交易 API 查询所有合约"""
import sys
sys.path.insert(0, r'E:\Develop\projects\ctp\runtime\td_tts')
import thosttraderapi as tdapi
import time

FRONT = "tcp://trading.openctp.cn:30001"

class TdSpi(tdapi.CThostFtdcTraderSpi):
    def __init__(self):
        super().__init__()
        self.api = None
        self.instruments = {}
        self.done = False
        self.login_ok = False

    def run(self):
        self.api = tdapi.CThostFtdcTraderApi.CreateFtdcTraderApi()
        self.api.RegisterFront(FRONT)
        self.api.RegisterSpi(self)
        self.api.SubscribePublicTopic(tdapi.THOST_TERT_QUICK)
        self.api.SubscribePrivateTopic(tdapi.THOST_TERT_QUICK)
        self.api.Init()

    def OnFrontConnected(self):
        print("Front Connected", flush=True)
        req = tdapi.CThostFtdcReqUserLoginField()
        # 7x24 has no broker/user/auth
        req.BrokerID = ""
        req.UserID = ""
        req.Password = ""
        self.api.ReqUserLogin(req, 0)

    def OnFrontDisconnected(self, n):
        print(f"Disconnected n={n}", flush=True)

    def OnRspUserLogin(self, p, info, req, last):
        if info and info.ErrorID != 0:
            print(f"Login failed: {info.ErrorID} {info.ErrorMsg}", flush=True)
            self.done = True
            return
        print(f"Login OK. TradingDay={p.TradingDay}", flush=True)
        self.login_ok = True
        # Query all instruments - no exchange/product filter
        qry = tdapi.CThostFtdcQryInstrumentField()
        qry.ExchangeID = ""
        qry.ProductID = ""
        qry.InstrumentID = ""
        self.api.ReqQryInstrument(qry, 0)

    def OnRspQryInstrument(self, p, info, req, last):
        if p:
            inst = p.InstrumentID
            self.instruments[inst] = {
                'exchange': p.ExchangeID,
                'product': p.ProductID,
                'name': p.InstrumentName.decode('gbk') if isinstance(p.InstrumentName, bytes) else p.InstrumentName,
                'vol': p.VolumeMultiple,
                'price': p.PriceTick,
            }
        if last:
            self._report()

    def _report(self):
        from collections import defaultdict
        by_product = defaultdict(list)
        for inst, d in sorted(self.instruments.items()):
            by_product[d['product']].append(inst)

        print(f"\n{'='*60}", flush=True)
        print(f"共查到 {len(self.instruments)} 个合约", flush=True)
        print(f"{'='*60}", flush=True)
        for prod, insts in sorted(by_product.items()):
            print(f"\n[{prod}] ({len(insts)}): {', '.join(insts[:10])}", end="", flush=True)
            if len(insts) > 10:
                print(f" ... +{len(insts)-10} more", end="", flush=True)
            print(flush=True)
        self.done = True
        self.api.Release()

    def OnRspError(self, info, req, last):
        print(f"RspError: {info.ErrorID} {info.ErrorMsg}", flush=True)
        if last:
            self.done = True

def main():
    print(f"API: {tdapi.CThostFtdcTraderApi.GetApiVersion()}", flush=True)
    print(f"Front: {FRONT}", flush=True)
    spi = TdSpi()
    spi.run()
    while not spi.done:
        time.sleep(0.5)
    print(f"\nTotal instruments: {len(spi.instruments)}", flush=True)

if __name__ == "__main__":
    sys.exit(main())
