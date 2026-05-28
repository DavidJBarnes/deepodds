from pydantic import BaseModel


class CalibrationBin(BaseModel):
    bin_label: str
    bin_low: float
    bin_high: float
    count: int
    wins: int
    avg_model_prob: float
    actual_win_rate: float


class CalibrationResponse(BaseModel):
    bins: list[CalibrationBin]
    total_samples: int
    brier_score: float
    reliability_ready: bool
class RetrainResponse(BaseModel):
    success: bool
    message: str
    model_file_size_kb: float
