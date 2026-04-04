"""扫描 SimNow 7x24 环境支持的合约列表"""
import sys
import time
from pathlib import Path
sys.path.insert(0, r"E:\Develop\projects\ctp\runtime\md_simnow")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import thostmduserapi as mdapi
from runtime.front_config import resolve_ctp_connection

DEFAULT_FRONT = "tcp://182.254.243.31:40011"

# 全品种合集（上海/大连/郑州/中金所主力+次主力）
CONTRACTS = [
    # 黑色系
    'rb2605','rb2606','rb2607','rb2608','rb2609','rb2610','rb2611','rb2612',
    'hc2605','hc2606','hc2607','hc2608','hc2609','hc2610','hc2611','hc2612',
    'i2605','i2606','i2607','i2608','i2609','i2610','i2611','i2612',
    'j2605','j2606','j2607','j2608','j2609','j2610','j2611','j2612',
    'jm2605','jm2606','jm2607','jm2608','jm2609','jm2610','jm2611','jm2612',
    # 有色金属
    'cu2605','cu2606','cu2607','cu2608','cu2609','cu2610','cu2611','cu2612',
    'al2605','al2606','al2607','al2608','al2609','al2610','al2611','al2612',
    'zn2605','zn2606','zn2607','zn2608','zn2609','zn2610','zn2611','zn2612',
    'pb2605','pb2606','pb2607','pb2608','pb2609','pb2610','pb2611','pb2612',
    'ni2605','ni2606','ni2607','ni2608','ni2609','ni2610','ni2611','ni2612',
    'sn2605','sn2606','sn2607','sn2608','sn2609','sn2610','sn2611','sn2612',
    'ss2605','ss2606','ss2607','ss2608','ss2609','ss2610','ss2611','ss2612',
    # 贵金属
    'au2604','au2606','au2608','au2610','au2612',
    'ag2604','ag2606','ag2608','ag2610','ag2612',
    # 能源化工
    'sc2605','sc2606','sc2607','sc2608','sc2609','sc2610','sc2611','sc2612',
    'ru2605','ru2606','ru2607','ru2608','ru2609','ru2610','ru2611','ru2612',
    'bu2605','bu2606','bu2607','bu2608','bu2609','bu2610','bu2611','bu2612',
    'pg2605','pg2606','pg2607','pg2608','pg2609','pg2610','pg2611','pg2612',
    'eb2605','eb2606','eb2607','eb2608','eb2609','eb2610','eb2611','eb2612',
    'eg2605','eg2606','eg2607','eg2608','eg2609','eg2610','eg2611','eg2612',
    'ma2605','ma2607','ma2609','ma2611',
    'ta2605','ta2607','ta2609','ta2611',
    'fg2605','fg2607','fg2609','fg2611',
    'pf2605','pf2607','pf2609','pf2611',
    'rm2605','rm2607','rm2609','rm2611',
    'sr2605','sr2607','sr2609','sr2611',
    'cf2605','cf2607','cf2609','cf2611',
    'cy2605','cy2607','cy2609','cy2611',
    'oi2605','oi2607','oi2609','oi2611',
    'wh2605','wh2607','wh2609','wh2611',
    'pm2605','pm2607','pm2609','pm2611',
    # 大连农产品
    'm2605','m2607','m2608','m2609','m2611','m2612',
    'y2605','y2607','y2608','y2609','y2611','y2612',
    'c2605','c2607','c2609','c2611','c2612',
    'cs2605','cs2607','cs2609','cs2611','cs2612',
    'p2605','p2607','p2608','p2609','p2610','p2611',
    'a2605','a2607','a2609','a2611',
    'b2605','b2607','b2609','b2611',
    # 塑料聚烯烃
    'l2605','l2607','l2608','l2609','l2611','l2612',
    'pp2605','pp2606','pp2607','pp2608','pp2609','pp2610','pp2611','pp2612',
    'v2605','v2607','v2608','v2609','v2611','v2612',
    # 中金所股指
    'if2604','if2605','if2606','if2609',
    'ih2604','ih2605','ih2606','ih2609',
    'ic2604','ic2605','ic2606','ic2609',
    'im2604','im2605','im2606','im2609',
    'tf2606','tf2609','tf2612',
    'ts2606','ts2609','ts2612',
    't2606','t2609','t2612',
]


class Scanner(mdapi.CThostFtdcMdSpi):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.api = None
        self.success = []
        self.fail = []
        self.pending = set(CONTRACTS)
        self.login_done = False

    def run(self):
        self.api = mdapi.CThostFtdcMdApi.CreateFtdcMdApi()
        self.api.RegisterFront(self.settings.front)
        self.api.RegisterSpi(self)
        self.api.Init()

    def OnFrontConnected(self):
        print("Front Connected", flush=True)
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
        if pRspInfo and pRspInfo.ErrorID != 0:
            print(f"Authenticate failed: {pRspInfo.ErrorID} {pRspInfo.ErrorMsg}", flush=True)
            return
        print("Authenticate OK", flush=True)
        req = mdapi.CThostFtdcReqUserLoginField()
        req.BrokerID = self.settings.broker_id
        req.UserID = self.settings.user_id
        req.Password = self.settings.password
        self.api.ReqUserLogin(req, 1)

    def OnFrontDisconnected(self, nReason):
        print(f"Disconnected nReason={nReason}", flush=True)

    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID, bIsLast):
        if pRspInfo and pRspInfo.ErrorID != 0:
            print(f"Login failed: {pRspInfo.ErrorID} {pRspInfo.ErrorMsg}", flush=True)
            return
        print(f"Login OK. TradingDay={pRspUserLogin.TradingDay}", flush=True)
        self.login_done = True
        symbols = [s.encode('utf-8') for s in CONTRACTS]
        self.api.SubscribeMarketData(symbols, len(symbols))

    def OnRspSubMarketData(self, pSpecificInstrument, pRspInfo, nRequestID, bIsLast):
        inst = pSpecificInstrument.InstrumentID
        self.pending.discard(inst)
        if pRspInfo is None or pRspInfo.ErrorID == 0:
            self.success.append(inst)
        else:
            msg = pRspInfo.ErrorMsg.decode('utf-8').strip() if isinstance(pRspInfo.ErrorMsg, bytes) else str(pRspInfo.ErrorMsg).strip()
            self.fail.append((inst, pRspInfo.ErrorID, msg))

        if not self.pending:
            self._report()

    def OnRtnDepthMarketData(self, pDepthMarketData):
        pass  # ignore ticks during scan

    def _report(self):
        print(f"\n{'='*60}", flush=True)
        print(f"扫描完成  成功: {len(self.success)}  失败: {len(self.fail)}", flush=True)
        print(f"{'='*60}", flush=True)
        if self.success:
            print(f"\n[成功订阅 {len(self.success)} 个合约]:", flush=True)
            # group by first 2 chars (category)
            from collections import defaultdict
            by_cat = defaultdict(list)
            for s in sorted(self.success):
                by_cat[s[:2]].append(s)
            for cat, items in sorted(by_cat.items()):
                print(f"  {cat}: {', '.join(items)}", flush=True)
        if self.fail:
            print(f"\n[订阅失败 {len(self.fail)} 个]:", flush=True)
            for inst, err, msg in self.fail[:20]:
                print(f"  {inst}  err={err} {msg}", flush=True)
            if len(self.fail) > 20:
                print(f"  ... 还有 {len(self.fail)-20} 个", flush=True)
        print(f"{'='*60}", flush=True)
        self.api.Release()


def main():
    settings = resolve_ctp_connection(DEFAULT_FRONT)
    print(f"API: {mdapi.CThostFtdcMdApi.GetApiVersion()}", flush=True)
    print(f"Front: {settings.front} ({settings.front_source})", flush=True)
    if len(settings.front_candidates) > 1:
        print(f"Front pool: {', '.join(settings.front_candidates)}", flush=True)
    print(f"Auth source: {settings.auth_source}", flush=True)
    if settings.redis_error:
        print(f"Redis config warning: {settings.redis_error}", flush=True)
    print(f"Total contracts to scan: {len(CONTRACTS)}\n", flush=True)
    scanner = Scanner(settings)
    scanner.run()
    # wait up to 30s for scan to finish
    start = time.time()
    while scanner.pending and time.time() - start < 30:
        time.sleep(0.5)
    if scanner.pending:
        print(f"\n超时，还有 {len(scanner.pending)} 个未收到响应: {list(scanner.pending)[:10]}", flush=True)
    else:
        # give a moment for last callbacks
        time.sleep(1)

if __name__ == "__main__":
    sys.exit(main())
