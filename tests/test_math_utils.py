import pytest
import numpy as np
from analysis_bot.services.math_utils import MathUtils


class TestMathUtilsQuartile:
    def test_quartile_with_valid_data(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        result = MathUtils.quartile(data)
        
        assert len(result) == 4  # 25%, 50%, 75%, mean
        assert all(isinstance(x, (int, float)) for x in result)
        
    def test_quartile_with_empty_list(self):
        with pytest.raises(ValueError, match="Input data cannot be empty"):
            MathUtils.quartile([])
    
    def test_quartile_with_none_values(self):
        data = [1.0, 2.0, None, 4.0, 5.0]
        result = MathUtils.quartile(data)
        assert len(result) == 4
    
    def test_quartile_with_nan_values(self):
        data = [1.0, 2.0, np.nan, 4.0, 5.0]
        result = MathUtils.quartile(data)
        assert len(result) == 4


class TestMathUtilsPercentileRank:
    def test_percentile_rank_with_valid_data(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = MathUtils.percentile_rank(data, 3.0)
        
        assert isinstance(result, float)
        assert 0 <= result <= 100
        
    def test_percentile_rank_with_empty_list(self):
        result = MathUtils.percentile_rank([], 3.0)
        assert result == 50.0
    
    def test_percentile_rank_with_none_value(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = MathUtils.percentile_rank(data, None)
        assert result == 50.0
    
    def test_percentile_rank_with_none_values_in_data(self):
        data = [1.0, 2.0, None, 4.0, 5.0]
        result = MathUtils.percentile_rank(data, 3.0)
        assert isinstance(result, float)
        assert 0 <= result <= 100


class TestMathUtilsMeanReversion:
    def test_mean_reversion_with_valid_data(self):
        data = [100.0, 105.0, 110.0, 108.0, 112.0, 115.0]
        result = MathUtils.mean_reversion(data)
        
        assert isinstance(result, dict)
        assert "prob" in result
        assert "TL" in result
        assert "expect" in result
        assert "targetprice" in result
        assert "bands" in result
        assert len(result["prob"]) == 3
        assert len(result["expect"]) == 3
        
    def test_mean_reversion_with_empty_list(self):
        result = MathUtils.mean_reversion([])
        assert result == {}
    
    def test_mean_reversion_with_none_values(self):
        data = [100.0, 105.0, None, 108.0, 112.0]
        result = MathUtils.mean_reversion(data)
        assert isinstance(result, dict)
        assert "prob" in result
    
    def test_mean_reversion_with_nan_values(self):
        data = [100.0, 105.0, np.nan, 108.0, 112.0]
        result = MathUtils.mean_reversion(data)
        assert isinstance(result, dict)
        assert "prob" in result


class TestMathUtilsGenerateBandLabels:
    def test_generate_band_labels(self):
        labels = MathUtils._generate_band_labels()
        
        assert isinstance(labels, list)
        assert len(labels) == 7
        assert "TL+3SD" in labels
        assert "TL+2SD" in labels
        assert "TL+1SD" in labels
        assert "TL" in labels
        assert "TL-1SD" in labels
        assert "TL-2SD" in labels
        assert "TL-3SD" in labels
