"""
app/models/pipeline_run.py
Model for tracking observability metrics of search/discovery pipeline runs.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Float, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    search_query: Mapped[str] = mapped_column(String(255))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    
    total_discovered: Mapped[int] = mapped_column(Integer, default=0)
    skipped_duplicates: Mapped[int] = mapped_column(Integer, default=0)
    enrichment_failures: Mapped[int] = mapped_column(Integer, default=0)
    llm_failures: Mapped[int] = mapped_column(Integer, default=0)
    successfully_processed: Mapped[int] = mapped_column(Integer, default=0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "search_query": self.search_query,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "total_discovered": self.total_discovered,
            "skipped_duplicates": self.skipped_duplicates,
            "enrichment_failures": self.enrichment_failures,
            "llm_failures": self.llm_failures,
            "successfully_processed": self.successfully_processed,
            "duplicate_rate": round(self.skipped_duplicates / self.total_discovered, 2) if self.total_discovered > 0 else 0,
            "failure_rate": round((self.enrichment_failures + self.llm_failures) / self.total_discovered, 2) if self.total_discovered > 0 else 0
        }
