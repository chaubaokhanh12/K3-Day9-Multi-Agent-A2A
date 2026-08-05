"""CoordinatorAgent - dieu phoi toan bo luong xu ly mot case.

Luong handoff:
    FactExtractor
        -> 3 domain agent chay song song (moi agent mot lat cat du lieu)
        -> PolicyAgent (deterministic, co tham quyen)  ||  IndependentReview (LLM, mu)
        -> Adjudicator (hoa giai, hieu chinh confidence)
        -> EvidenceCurator
        -> Verifier
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .agents import (
    AdjudicatorAgent,
    DeliveryTimelineAgent,
    EvidenceCuratorAgent,
    IndependentReviewAgent,
    OrderIntegrityAgent,
    PaymentReconciliationAgent,
    VerifierAgent,
)
from .data_store import store
from .facts import FactExtractor
from .llm_client import LLMClient
from .policy_engine import PolicyAgent, financials
from .trace import TraceWriter


class CoordinatorAgent:
    name = "CoordinatorAgent"

    def __init__(self, llm: LLMClient | None = None, trace: TraceWriter | None = None):
        self.llm = llm or LLMClient()
        self.trace = trace
        self.fact_extractor = FactExtractor()
        self.domain_agents = [
            OrderIntegrityAgent(self.llm),
            DeliveryTimelineAgent(self.llm),
            PaymentReconciliationAgent(self.llm),
        ]
        self.policy = PolicyAgent()
        self.review = IndependentReviewAgent(self.llm)
        self.adjudicator = AdjudicatorAgent()
        self.curator = EvidenceCuratorAgent()
        self.verifier = VerifierAgent()

    def _emit(self, *args, **kwargs) -> None:
        if self.trace:
            self.trace.emit(*args, **kwargs)

    def run_case(self, case: dict) -> dict:
        case_id = case["case_id"]
        order_id = case["customer_request"]["claimed_order_id"]
        step = 0

        self._emit(
            case_id,
            self.name,
            step,
            "case_received",
            handoff_to="FactExtractor",
            payload={
                "claimed_order_id": order_id,
                "policy_version": case.get("policy_version"),
                "language": case["customer_request"].get("language"),
            },
        )

        # -- 1. facts ------------------------------------------------------
        step += 1
        bundle = store.get_case_bundle(order_id)
        facts = self.fact_extractor.run(case_id, bundle)
        self._emit(
            case_id,
            "FactExtractor",
            step,
            "facts_extracted",
            handoff_to="DomainAgents",
            payload={
                "order_found": facts.order_found,
                "facts": facts.to_prompt_dict(),
                "evidence_registry_size": len(facts.registry.all_ids()),
                "data_gaps": facts.data_gaps,
            },
        )

        # -- 2. domain agent song song --------------------------------------
        step += 1
        with ThreadPoolExecutor(max_workers=len(self.domain_agents)) as pool:
            findings = list(pool.map(lambda a: a.run(facts), self.domain_agents))
        for f in findings:
            self._emit(
                case_id,
                f.agent,
                step,
                "finding_ready",
                handoff_to="PolicyAgent|IndependentReviewAgent",
                payload=f.to_trace(),
            )

        # -- 3a. policy deterministic (co tham quyen) -----------------------
        step += 1
        verdict = self.policy.run(facts)
        self._emit(
            case_id,
            "PolicyAgent",
            step,
            "verdict_deterministic",
            handoff_to="AdjudicatorAgent",
            payload={
                "primary_issue": verdict.primary_issue,
                "rule_id": verdict.rule_id,
                "case_status": verdict.case_status,
                "root_causes": verdict.root_causes,
                "responsible_parties": verdict.responsible_parties,
                "recommended_refund_brl": verdict.recommended_refund_brl,
                "rationale": verdict.rationale,
            },
        )

        # -- 3b. phuc tham doc lap (mu voi verdict o tren) ------------------
        review = self.review.run(findings)
        self._emit(
            case_id,
            "IndependentReviewAgent",
            step,
            "verdict_independent",
            handoff_to="AdjudicatorAgent",
            payload=review,
        )

        # -- 4. hoa giai -----------------------------------------------------
        step += 1
        adjudication = self.adjudicator.run(facts, verdict, findings, review)
        self._emit(
            case_id,
            "AdjudicatorAgent",
            step,
            "adjudicated",
            handoff_to="EvidenceCuratorAgent",
            payload=adjudication,
        )

        # -- 5. chon evidence ------------------------------------------------
        step += 1
        curated = self.curator.run(facts, verdict)
        self._emit(
            case_id,
            "EvidenceCuratorAgent",
            step,
            "evidence_curated",
            handoff_to="VerifierAgent",
            payload=curated,
        )

        # -- 6. dung bao cao -------------------------------------------------
        report = {
            "case_id": case_id,
            "assessment": {
                "primary_issue": verdict.primary_issue,
                "case_status": verdict.case_status,
                "confidence": adjudication["confidence"],
            },
            "affected_entities": curated["affected_entities"],
            "root_cause_analysis": {
                "ranked_causes": [
                    {"cause_code": code, "rank": i}
                    for i, code in enumerate(verdict.root_causes, start=1)
                ],
                "responsible_parties": verdict.responsible_parties,
            },
            "evidence_ids": curated["evidence_ids"],
            "financial_resolution": financials(facts, verdict),
            "resolution_actions": verdict.actions,
        }

        # -- 7. kiem tra cuoi -------------------------------------------------
        step += 1
        checked = self.verifier.run(report, facts)
        self._emit(
            case_id,
            "VerifierAgent",
            step,
            "verified",
            handoff_to="CoordinatorAgent",
            payload={
                "passed": checked["passed"],
                "violations": checked["violations"],
                "repairs": checked["repairs"],
            },
        )

        step += 1
        self._emit(
            case_id,
            self.name,
            step,
            "case_finalized",
            handoff_to=None,
            payload={
                "primary_issue": checked["report"]["assessment"]["primary_issue"],
                "confidence": checked["report"]["assessment"]["confidence"],
                "recommended_refund_brl": checked["report"]["financial_resolution"][
                    "recommended_refund_brl"
                ],
                "verifier_passed": checked["passed"],
                "review_agreement": adjudication["agreement"],
            },
        )

        return {
            "report": checked["report"],
            "verifier": checked,
            "adjudication": adjudication,
            "verdict": verdict,
            "facts": facts,
        }
