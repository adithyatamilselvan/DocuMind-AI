from pydantic import BaseModel, Field


class Point(BaseModel):
    text: str = Field(max_length=600)
    sources: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Source labels like D1A2S3 that support this point",
    )


class AspectComparison(BaseModel):
    aspect: str = Field(max_length=80)
    similarities: list[Point] = Field(default_factory=list, max_length=6)
    differences: list[Point] = Field(default_factory=list, max_length=8)
    conflicts: list[Point] = Field(
        default_factory=list,
        max_length=6,
        description="Statements that directly contradict each other",
    )
    missing_information: list[Point] = Field(
        default_factory=list,
        max_length=6,
        description="Things one document covers and another omits",
    )


class ComparisonResult(BaseModel):
    summary: str = Field(max_length=1500)
    aspects: list[AspectComparison] = Field(default_factory=list, max_length=8)


class VersionSummary(BaseModel):
    summary: str = Field(max_length=1200)
    notable_changes: list[str] = Field(default_factory=list, max_length=10)
