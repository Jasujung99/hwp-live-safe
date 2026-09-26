# 후속 후보 정리: safe의 경계

이번 PR은 로컬 수동 릴리스 probe의 **native 검증 순서**를
[native_release_gate.py](../scripts/native_release_gate.py)로 승격한다.
COM worker는 시작 시 확인한 비저장 문서의 COM 식별자를 보존하고 이후
읽기·작성·Undo 전에 활성 문서가 같은 대상인지 확인한다.

- 호출자 Python/MCP 2.x 환경을 사용하며 개인 경로나 인터프리터를 고정하지 않는다.
- 임시 빈 프로필 디렉터리를 사용한다. 프로필 값을 읽거나 삽입하지 않는다.
- 새 문서 생성, read → preview → 명시적 확인 → apply, 제한 Undo,
  수동 변경 후 stale preview/Undo 거부를 검사한다.
- 기존 창 자동 선택과 foreground 입력은 포함하지 않는다. 문서 저장·닫기도 하지 않는다.
- 입력은 합성 제목과 2×2 표뿐이다. 실제 문서와 수동 입력을 눈으로 확인해야 한다.
- 취소/실패 시 자동으로 더 편집하거나 사용자 문서를 정리하지 않는다.
- 게이트는 새 문서 ID를 출력한다. 성공 시 남은 `MANUAL-STALE`, `UNDO-GATE`,
  `MANUAL-UNDO` 표식으로 새 창을 확인하고 **그 창만 저장하지 않고 닫는다**.
  식별할 수 없다면 창을 그대로 둔다. 앞선 제목·표는 게이트가 Undo한다.

## 검증 증거

로컬 자동 회귀 **49 passed**, 빈 임시 프로필을 이용한 fake stdio MCP **15 tools**,
공개 파일 검사, 현재 변경의 wheel/sdist 빌드·패키지 검사 통과. 게이트 전용 9개 테스트는
실제 service와 FakeHwpBackend로 순서·revision·취소·문서 식별 실패를 확인했다.
PowerShell worker 구문 검사도 통과했다. 현재 head의 Windows CI는 PR 갱신 후
재검증해야 한다.

새 비저장 합성 문서에서 실제 COM/MCP `tests/mcp_live_smoke.py`의 read → preview →
apply, 2×2 표, Undo가 통과했다. 별도 새 비저장 합성 문서에서
`scripts/native_external_change_gate.py --live`가 서비스 밖의 native backend
편집을 이용하여 오래된 preview와 Undo의 `DOCUMENT_CHANGED` 거부 및 내용 보존을
확인했다. 두 실행은 서로 다른 owned 문서 ID를 출력했고 저장하거나 닫지 않았다.
두 번째 검사는 외부 변경 감지 계약을 검증하지만 **수동 타이핑·화면 확인은 아니다**.
`native_release_gate.py`의 수동 화면 게이트는 아직 실행하지 않았으며 fake나
자동 native 검사를 시각 검증으로 표시하지 않는다.

## hwpctl과의 관계

hwpctl의 패키지·입출력 / 문서 모델 / 구성·조판 / 검증이라는 4계층은 safe에 새
작성 엔진을 연결하는 약속이 아니다. 이 스크립트는 **검증 하네스**이고 런타임 API는
그대로다. 세션·문서·revision·Undo·잠금은 다른 엔진과 공유하지 않는다.
공개 도구 목록은 유지하고 worker의 문서 소유권 검사를 강화했다.
