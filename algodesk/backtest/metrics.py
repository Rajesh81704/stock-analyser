"""
Trade metrics and performance analysis
"""
import pandas as pd
import numpy as np
from typing import List, Dict


class TradeMetrics:
    """Calculate metrics from trade list"""
    
    @staticmethod
    def from_trades(trades: List[Dict]) -> Dict:
        """
        Calculate comprehensive metrics from trade list.
        
        Args:
            trades: List of trade dicts with keys: gross_pnl, net_pnl, entry_date, exit_date, kind, etc
        
        Returns:
            Dict with all metrics
        """
        if not trades:
            return TradeMetrics._empty_metrics()
        
        df = pd.DataFrame(trades)
        
        # Separate wins and losses
        wins = df[df['net_pnl'] > 0]
        losses = df[df['net_pnl'] <= 0]
        
        num_trades = len(df)
        num_wins = len(wins)
        num_losses = len(losses)
        
        # Win rate
        win_rate = (num_wins / num_trades) if num_trades > 0 else 0
        
        # P&L metrics
        total_pnl = df['net_pnl'].sum()
        gross_pnl = df['gross_pnl'].sum()
        total_costs = df['costs'].sum() if 'costs' in df.columns else 0
        
        # Wins and losses
        sum_wins = wins['net_pnl'].sum() if len(wins) > 0 else 0
        sum_losses = abs(losses['net_pnl'].sum()) if len(losses) > 0 else 0
        
        avg_win = sum_wins / num_wins if num_wins > 0 else 0
        avg_loss = sum_losses / num_losses if num_losses > 0 else 0
        
        # Profit factor
        profit_factor = (sum_wins / sum_losses) if sum_losses > 0 else float('inf') if sum_wins > 0 else 0
        
        # Risk metrics (in R - reward/risk units)
        if 'risk' in df.columns and 'net_pnl' in df.columns:
            df['r_multiple'] = df['net_pnl'] / df['risk']
            expectancy_r = df['r_multiple'].mean()
            avg_win_r = wins['r_multiple'].mean() if len(wins) > 0 else 0
            avg_loss_r = -losses['r_multiple'].mean() if len(losses) > 0 else 0
        else:
            expectancy_r = 0
            avg_win_r = 0
            avg_loss_r = 0
        
        # Holding period
        if 'holding_days' in df.columns:
            avg_holding_days = df['holding_days'].mean()
        else:
            avg_holding_days = 0
        
        # Consecutive losses
        df['is_loss'] = df['net_pnl'] <= 0
        max_consecutive_losses = TradeMetrics._max_streak(df['is_loss'].values)
        
        # By setup type
        setup_a_trades = len(df[df['kind'] == 'A_pullback']) if 'kind' in df.columns else 0
        setup_b_trades = len(df[df['kind'] == 'B_breakout']) if 'kind' in df.columns else 0
        
        setup_a_wr = (len(wins[wins['kind'] == 'A_pullback']) / setup_a_trades) if setup_a_trades > 0 else 0
        setup_b_wr = (len(wins[wins['kind'] == 'B_breakout']) / setup_b_trades) if setup_b_trades > 0 else 0
        
        return {
            'num_trades': num_trades,
            'num_wins': num_wins,
            'num_losses': num_losses,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'gross_pnl': gross_pnl,
            'total_costs': total_costs,
            'sum_wins': sum_wins,
            'sum_losses': sum_losses,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'expectancy_r': expectancy_r,
            'avg_win_r': avg_win_r,
            'avg_loss_r': avg_loss_r,
            'avg_holding_days': avg_holding_days,
            'max_consecutive_losses': max_consecutive_losses,
            'setup_a_trades': setup_a_trades,
            'setup_a_win_rate': setup_a_wr,
            'setup_b_trades': setup_b_trades,
            'setup_b_win_rate': setup_b_wr,
        }
    
    @staticmethod
    def _max_streak(is_loss_array) -> int:
        """Calculate longest consecutive True values"""
        max_streak = 0
        current_streak = 0
        for val in is_loss_array:
            if val:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        return max_streak
    
    @staticmethod
    def _empty_metrics() -> Dict:
        """Return empty metrics dict"""
        return {
            'num_trades': 0,
            'num_wins': 0,
            'num_losses': 0,
            'win_rate': 0,
            'total_pnl': 0,
            'gross_pnl': 0,
            'total_costs': 0,
            'sum_wins': 0,
            'sum_losses': 0,
            'avg_win': 0,
            'avg_loss': 0,
            'profit_factor': 0,
            'expectancy_r': 0,
            'avg_win_r': 0,
            'avg_loss_r': 0,
            'avg_holding_days': 0,
            'max_consecutive_losses': 0,
            'setup_a_trades': 0,
            'setup_a_win_rate': 0,
            'setup_b_trades': 0,
            'setup_b_win_rate': 0,
        }


class EquityCurve:
    """Manage equity curve"""
    
    @staticmethod
    def calculate_drawdown(equity_series: pd.Series) -> Dict:
        """
        Calculate max drawdown and related stats.
        
        Args:
            equity_series: Series of daily equity values
        
        Returns:
            Dict with drawdown metrics
        """
        cummax = equity_series.cummax()
        drawdown = (equity_series - cummax) / cummax
        
        max_dd = drawdown.min()
        max_dd_pct = max_dd * 100
        
        # Drawdown duration
        dd_periods = 0
        max_dd_duration = 0
        for val in drawdown:
            if val < 0:
                dd_periods += 1
            else:
                max_dd_duration = max(max_dd_duration, dd_periods)
                dd_periods = 0
        
        return {
            'max_drawdown': max_dd_pct,
            'max_drawdown_duration_days': max_dd_duration,
            'drawdown_series': drawdown
        }
    
    @staticmethod
    def calculate_returns(equity_start: float, equity_end: float, num_days: int) -> Dict:
        """
        Calculate return metrics.
        
        Args:
            equity_start: Starting equity
            equity_end: Ending equity
            num_days: Number of trading days
        
        Returns:
            Dict with return metrics
        """
        total_return = (equity_end - equity_start) / equity_start if equity_start > 0 else 0
        total_return_pct = total_return * 100
        
        # Annualized return (assuming 252 trading days/year)
        years = num_days / 252
        if years > 0:
            annualized_return = (equity_end / equity_start) ** (1 / years) - 1
            annualized_return_pct = annualized_return * 100
        else:
            annualized_return_pct = 0
        
        return {
            'total_return': total_return,
            'total_return_pct': total_return_pct,
            'annualized_return_pct': annualized_return_pct,
            'cagr': annualized_return_pct  # Same as annualized
        }
