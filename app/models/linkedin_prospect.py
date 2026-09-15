"""
app/models/linkedin_prospect.py
ORM models for LinkedIn prospects and generated outreach drafts.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database import Base

# Use JSONB for Postgres; JSON for SQLite
JsonType = JSONB if False else JSON  # switched at runtime via dialect check


def _json_type():
    """Return JSONB on Postgres, JSON on SQLite."""
    from app.config import get_settings
    s = get_settings()
    if s.is_sqlite:
        from sqlalchemy import JSON
        return JSON
    from sqlalchemy.dialects.postgresql import JSONB
    return JSONB


class ProspectStatus(str, enum.Enum):
    DISCOVERED = "DISCOVERED"
    ENRICHED = "ENRICHED"
    QUALIFIED = "QUALIFIED"
    DRAFTED = "DRAFTED"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ROUTED = "ROUTED"
    EXPORTED = "EXPORTED"
    CONTACTED = "CONTACTED"
    REPLIED = "REPLIED"
    ENRICHMENT_FAILED = "ENRICHMENT_FAILED"
    LLM_FAILED = "LLM_FAILED"
    CRM_EXPORT_FAILED = "CRM_EXPORT_FAILED"


class LinkedInProspect(Base):
    __tablename__ = "linkedin_prospects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # ── Core identity ───────────────────────────────────────────────────────────
    linkedin_url: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    full_name: Mapped[str | None] = mapped_column(Text)
    headline: Mapped[str | None] = mapped_column(Text)
    current_title: Mapped[str | None] = mapped_column(Text)
    current_company: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)

    # ── Enriched signals ────────────────────────────────────────────────────────
    tenure_months: Mapped[int | None] = mapped_column(Integer)
    recent_post_snippet: Mapped[str | None] = mapped_column(Text)
    role_change_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    education: Mapped[dict | None] = mapped_column(JSON)      # [{school, degree, year}]
    raw_profile: Mapped[dict | None] = mapped_column(JSON)    # full Proxycurl payload

    # ── Qualification ───────────────────────────────────────────────────────────
    fit_score: Mapped[float | None] = mapped_column(Float)    # 0.0 – 1.0 (now deterministic)
    fit_label: Mapped[str | None] = mapped_column(String(20)) # strong/possible/weak
    reasons: Mapped[list | None] = mapped_column(JSON)        # LLM explainability reasons
    risks: Mapped[list | None] = mapped_column(JSON)          # LLM explainability risks

    # ── Routing ─────────────────────────────────────────────────────────────────
    owner: Mapped[str | None] = mapped_column(String(50))     # AE or BDR
    priority: Mapped[str | None] = mapped_column(String(20))  # P1, P2, P3
    routing_reason: Mapped[str | None] = mapped_column(Text)
    segment: Mapped[str | None] = mapped_column(String(50))
    next_action: Mapped[str | None] = mapped_column(String(255))

    # ── Metadata ────────────────────────────────────────────────────────────────
    search_query: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ProspectStatus] = mapped_column(
        Enum(ProspectStatus, name="prospectstatus", create_constraint=True),
        default=ProspectStatus.DISCOVERED,
        index=True
    )
    first_discovered: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    discovery_sources: Mapped[list | None] = mapped_column(JSON) # e.g., ["search1", "search2"]

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # ── Relationships ───────────────────────────────────────────────────────────
    outreach_drafts: Mapped[list["ProspectOutreachDraft"]] = relationship(
        back_populates="prospect", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "linkedin_url": self.linkedin_url,
            "full_name": self.full_name,
            "headline": self.headline,
            "current_title": self.current_title,
            "current_company": self.current_company,
            "location": self.location,
            "industry": self.industry,
            "tenure_months": self.tenure_months,
            "recent_post_snippet": self.recent_post_snippet,
            "role_change_detected": self.role_change_detected,
            "fit_score": self.fit_score,
            "fit_label": self.fit_label,
            "reasons": self.reasons or [],
            "risks": self.risks or [],
            "owner": self.owner,
            "priority": self.priority,
            "routing_reason": self.routing_reason,
            "segment": self.segment,
            "next_action": self.next_action,
            "search_query": self.search_query,
            "status": self.status.value if hasattr(self.status, "value") else self.status,
            "first_discovered": self.first_discovered.isoformat() if self.first_discovered else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "discovery_sources": self.discovery_sources or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ProspectOutreachDraft(Base):
    __tablename__ = "prospect_outreach_drafts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    prospect_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("linkedin_prospects.id", ondelete="CASCADE"), index=True
    )

    connection_note: Mapped[str | None] = mapped_column(Text)   # ≤300 chars
    followup_dm: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    approved: Mapped[bool] = mapped_column(Boolean, default=False)

    # ── Relationships ───────────────────────────────────────────────────────────
    prospect: Mapped["LinkedInProspect"] = relationship(
        back_populates="outreach_drafts",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "prospect_id": self.prospect_id,
            "connection_note": self.connection_note,
            "followup_dm": self.followup_dm,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "approved": self.approved,
        }
