import numpy as np
import statistics

class MathUtils:
    # Probabilities for standard deviation bands
    PROB_WEIGHTS = [0.001, 0.021, 0.136, 0.341, 0.341, 0.136, 0.021, 0.001]

    @staticmethod
    def _generate_band_labels() -> list[str]:
        """Generate labels for standard deviation bands."""
        return (
            [f"TL+{i}SD" for i in range(3, 0, -1)]
            + ["TL"]
            + [f"TL-{i}SD" for i in range(1, 4)]
        )

    @staticmethod
    def std(datas: list[float]):
        if not datas:
            raise ValueError("Input data cannot be empty")
        try:
            # Filter out None and NaN values
            datas = [d for d in datas if d is not None and not (isinstance(d, float) and np.isnan(d))]
            if not datas:
                return {}, []
            datas_np = np.array(datas, dtype=float)
        except ValueError:
            raise ValueError("Input data must contain only numeric values")

        result = {}
        # Simple median regression for TL (Trend Line) in standard deviation context 
        # (Legacy logic: uses median as baseline)
        tl_val = statistics.median(datas_np)
        result["TL"] = np.full_like(datas_np, tl_val)
        result["y-TL"] = datas_np - result["TL"]
        result["SD"] = np.std(result["y-TL"], ddof=1)  # Sample standard deviation
        
        sd = result["SD"]
        if sd == 0:
            sd = 1e-10  # Avoid division by zero

        for i in range(1, 4):
            result[f"TL-{i}SD"] = result["TL"] - i * sd
            result[f"TL+{i}SD"] = result["TL"] + i * sd
        
        # We process the final values for easy consumption
        final_result = {k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in result.items() if k not in ["y-TL", "SD"]}
        return final_result, MathUtils._generate_band_labels()

    @staticmethod
    def quartile(datas: list[float]) -> list[float]:
        if not datas:
            raise ValueError("Input data cannot be empty")
        # Filter out None and NaN values
        datas = [d for d in datas if d is not None and not (isinstance(d, float) and np.isnan(d))]
        if not datas:
            return []
            
        datas_np = np.array(datas, dtype=float)
        percentiles = [np.percentile(datas_np, p) for p in (25, 50, 75)]
        mean = float(np.mean(datas_np))
        return percentiles + [mean]

    @staticmethod
    def percentile_rank(datas: list[float], value: float) -> float:
        """Calculate the percentile rank of a value in the dataset (0-100)."""
        if not datas or value is None:
            return 50.0 # Default to middle if no data
            
        datas = [d for d in datas if d is not None and not (isinstance(d, float) and np.isnan(d))]
        if not datas:
            return 50.0
            
        datas_np = np.array(datas, dtype=float)
        # Calculate percentage of values less than the target value
        return float((datas_np < value).mean() * 100)

    @staticmethod
    def mean_reversion(prices: list[float]) -> dict:
        prices = [p for p in prices if p is not None and not np.isnan(p)]
        if not prices:
            return {}
            
        prices_np = np.array(prices, dtype=float)
        
        # Fit simple linear regression (avoid heavy sklearn dependency)
        idx = np.arange(1, len(prices_np) + 1)
        # np.polyfit returns slope, intercept for degree=1
        slope, intercept = np.polyfit(idx, prices_np, 1)

        # Calculate trend line and bands
        tl = intercept + idx * slope
        y_minus_tl = prices_np - tl
        sd = np.std(y_minus_tl, ddof=1)
        
        if sd == 0:
            sd = 1e-10

        bands = {}
        bands["TL"] = tl.tolist() if isinstance(tl, np.ndarray) else tl
        for i in range(1, 4):
            bands[f"TL-{i}SD"] = (tl - i * sd).tolist()
            bands[f"TL+{i}SD"] = (tl + i * sd).tolist()
            
        # Probability calculation
        last_price = prices_np[-1]
        band_labels = MathUtils._generate_band_labels()
        
        # Calculate probabilities based on current price position relative to bands
        # Legacy logic logic adapted
        up_prob = 0.0
        hold_prob = 0.0
        down_prob = sum(MathUtils.PROB_WEIGHTS) # Should be ~1.0
        
        # Simplified probability mapping (mimicking strict legacy logic)
        # Note: The legacy logic had a loop checking `last_price < result[band][-1]`
        # We need to construct the bands dict first with full arrays or just last values
        last_band_values = {k: v[-1] for k, v in bands.items()}
        last_band_values["TL"] = bands["TL"][-1]
        
        # Sort labels by value (High to Low typically, TL+3SD to TL-3SD)
        # band_labels is sorted TL+3SD ... TL ... TL-3SD
        
        for idx, band in enumerate(band_labels):
            band_val = last_band_values[band]
            weight = MathUtils.PROB_WEIGHTS[idx]
            
            if last_price < band_val:
                up_prob += weight
                down_prob -= weight
            else:
                hold_prob += weight
                down_prob -= weight
                break # Legacy logic breaks on first match?
                
        # Calculate expected values
        tl_last = last_band_values["TL"]
        tl_minus_3sd = last_band_values["TL-3SD"]
        tl_plus_3sd = last_band_values["TL+3SD"]
        
        expect_val_bull_1 = up_prob * (tl_last - last_price) - down_prob * last_price
        expect_val_bull_2 = up_prob * (tl_last - last_price) - down_prob * (last_price - tl_minus_3sd)
        expect_val_bear_1 = down_prob * (last_price - tl_last) - up_prob * (tl_plus_3sd - last_price)

        return {
            "prob": [up_prob * 100, hold_prob * 100, down_prob * 100],
            "TL": [float(tl_last)],
            "expect": [expect_val_bull_1, expect_val_bull_2, expect_val_bear_1],
            "targetprice": [float(last_band_values[title]) for title in band_labels],
            "bands": bands # Return full series for charting
        }
