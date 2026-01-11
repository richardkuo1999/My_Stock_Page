import pytest
from analysis_bot.services.math_utils import MathUtils


class TestMathUtilsStd:
    def test_std_with_valid_data(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        result, labels = MathUtils.std(data)
        
        assert isinstance(result, dict)
        assert "TL" in result
        assert "TL-1SD" in result
        assert "TL+1SD" in result
        assert isinstance(labels, list)
        
    def test_std_with_empty_list(self):
        with pytest.raises(ValueError, match="Input data cannot be empty"):
            MathUtils.std([])
    
    def test_std_with_none_values(self):
        data = [1.0, 2.0, None, 4.0, 5.0]
        result, _ = MathUtils.std(data)
        assert result is not None
        assert "TL" in result
    
    def test_std_with_nan_values(self):
        import numpy as np
        data = [1.0, 2.0, np.nan, 4.0, 5.0]
        result, _ = MathUtils.std(data)
        assert result is not None
        assert "TL" in result
