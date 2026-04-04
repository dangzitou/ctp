# openctp TTS 7x24 real-time market data

This directory is wired to the official openctp TTS 6.7.11 market-data DLL.

Default market front:

tcp://trading.openctp.cn:30011

Verified symbols on 2026-04-03:

- cu2605
- au2606

Run:

python E:\Develop\projects\ctp\runtime\md_tts\live_md_demo.py

Custom symbols:

python E:\Develop\projects\ctp\runtime\md_tts\live_md_demo.py --symbols cu2605,au2606

Custom duration:

python E:\Develop\projects\ctp\runtime\md_tts\live_md_demo.py --seconds 60

Notes:

- The local module in this directory uses the official openctp-tts v6.7.11 DLL, not the generic openctp-ctp wheel.
- If you see 4097, you are not loading the TTS DLL.
- Some symbols will return 无此合约; use valid current contracts.
