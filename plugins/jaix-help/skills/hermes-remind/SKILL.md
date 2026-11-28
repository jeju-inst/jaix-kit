---
name: hermes-remind
description: 리마인더·알림 예약. "리마인더 걸어 줘", "내일 9시에 알려 줘", "30분 뒤에 알림" 같은 요청에 쓴다. 셸 명령 `jaix hermes remind`(PATH)로 내 Hermes 봇이 그 시각에 내 슬랙 DM 으로 보내게 한다.
---

## 리마인더는 내 Hermes 봇으로 (2026-11-19)
- "리마인더 걸어 줘"류 요청은 슬랙 MCP 예약 메시지(slack_schedule_message)로 내 DM에 보내지 않는다. 내 Hermes 봇 리마인더로 건다: jaix hermes remind "<시각>" "<내용>" (시각은 2026-11-20T09:00 또는 in 30m).
- 이유: 슬랙 MCP 예약은 'Claude' 앱을 거쳐 "DM 시작 부분에만 추가" 안내가 뜨고, 본인 DM이라 알림도 약하다. 봇이 보내는 DM은 알림이 제대로 온다.
