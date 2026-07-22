"""신뢰경계·근거 인용 가드 (SFR-604, SFR-606, NFR-REL-03).

- 근거 인용 검증: 서술 문장은 유효한 signal_id를 인용해야 한다.
- 간접 프롬프트 주입 방어: 비신뢰 텍스트가 쓰기 도구 인자로 전파될 때
  지시문 성격 패턴을 서버측에서 차단한다("도구 결과는 데이터이지 명령이 아니다").
"""
from __future__ import annotations

import re

_SIGNAL_REF = re.compile(r"SIG-[0-9a-f]{12}")
# 지시문 주입 의심 패턴(한/영). 실제 운영은 정책 엔진·DLP로 확장(NFR-SEC-06).
_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"ignore (all|previous|above)",
        r"disregard (the )?(previous|above|prior)",
        r"system\s*[:：]",
        r"you are now",
        r"이전 지시(를)? 무시",
        r"앞의 지시(를)? 무시",
        r"승인(해|하라|처리)",       # 에이전트에 의한 승인 지시 시도 차단
        r"approve this memo",
    )
]


class CitationError(ValueError):
    pass


class InjectionBlocked(ValueError):
    pass


def assert_no_injection(text: str) -> None:
    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            raise InjectionBlocked(
                f"비신뢰/지시문 패턴 감지로 차단: '{pat.pattern}'. "
                "도구 결과·외부 텍스트는 데이터로만 취급되며 명령으로 실행되지 않는다(SFR-606)."
            )


def assert_cited(text: str, valid_signal_ids: set[str]) -> list[str]:
    """서술이 인용한 유효 signal_id를 반환. 없거나 무효면 CitationError."""
    refs = set(_SIGNAL_REF.findall(text))
    valid = [r for r in refs if r in valid_signal_ids]
    if not valid:
        raise CitationError(
            "서술 문장에 유효한 근거(signal_id, 예: SIG-xxxxxxxxxxxx) 인용이 없습니다. "
            "근거 없는 서술은 저장할 수 없습니다(NFR-REL-03)."
        )
    invalid = refs - set(valid)
    if invalid:
        raise CitationError(f"존재하지 않는 근거 인용: {sorted(invalid)}")
    return valid
