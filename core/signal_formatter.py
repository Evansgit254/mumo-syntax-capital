from core.filters.session_filter import SessionFilter

class SignalFormatter:
    """
    Formats raw strategy signals into comprehensive trading instructions.
    """
    
    @staticmethod
    def generate_reasoning(signal: dict) -> str:
        """
        Translates raw alpha factors and regime into beginner-friendly logic.
        Uses randomized phrases from REASONING_LIBRARY for variety.
        """
        # V17.4: Return existing reasoning if already generated (Consistency fix)
        if signal.get('reasoning'):
            return signal['reasoning']
            
        import random
        from core.reasoning_library import REASONING_LIBRARY
        
        score_details = signal.get('score_details', {})
        direction = signal.get('direction', 'N/A')
        regime = signal.get('regime', 'NORMAL')
        
        velocity = score_details.get('velocity', 0)
        zscore = score_details.get('zscore', 0)
        momentum = score_details.get('momentum', 0)
        
        reasons = []
        
        # 1. Market Context (The "Where are we?" part)
        if regime == "TRENDING":
            reasons.append(random.choice(REASONING_LIBRARY['CONTEXT']['TRENDING']))
        elif regime == "RANGING":
            reasons.append(random.choice(REASONING_LIBRARY['CONTEXT']['RANGING']))
            
        # 2. Key Drivers (The "Why now?" part)
        if direction == "BUY":
            # Pro-Buy Arguments
            if velocity > 0.5: 
                reasons.append(random.choice(REASONING_LIBRARY['BUY']['SPEED']))
            if zscore < -1.5: 
                reasons.append(random.choice(REASONING_LIBRARY['BUY']['DISCOUNT']))
            if momentum > 0.5: 
                reasons.append(random.choice(REASONING_LIBRARY['BUY']['STRENGTH']))
                
            # Anti-Sell Arguments (The "Why Not" part)
            # Pick 2 random reasons from the 'Why Not' list for variety
            why_not_list = REASONING_LIBRARY['BUY']['WHY_NOT_SELL']
            selected_why_nots = random.sample(why_not_list, min(2, len(why_not_list)))
            reasons.extend(selected_why_nots)
                
        else:
            # Pro-Sell Arguments
            if velocity < -0.5: 
                reasons.append(random.choice(REASONING_LIBRARY['SELL']['SPEED']))
            if zscore > 1.5: 
                reasons.append(random.choice(REASONING_LIBRARY['SELL']['PREMIUM']))
            if momentum < -0.5: 
                reasons.append(random.choice(REASONING_LIBRARY['SELL']['WEAKNESS']))
                
            # Anti-Buy Arguments (The "Why Not" part)
            # Pick 2 random reasons from the 'Why Not' list for variety
            why_not_list = REASONING_LIBRARY['SELL']['WHY_NOT_BUY']
            selected_why_nots = random.sample(why_not_list, min(2, len(why_not_list)))
            reasons.extend(selected_why_nots)
            
        if not reasons:
            reasons.append("✅ <b>Confirmation:</b> Multiple technical factors verify this entry.")
            
        # 3. Join with bullet points
        return "\n".join([f"• {r}" for r in reasons])

    @staticmethod
    def format_signal(signal: dict) -> str:
        """
        Convert raw signal into a comprehensive, educational trade instruction.
        """
        symbol = signal.get('symbol', 'UNKNOWN')
        direction = signal.get('direction', 'N/A')
        trade_type = signal.get('trade_type', 'TRADE')
        entry = signal.get('entry_price', 0)
        sl = signal.get('sl', 0)
        tp0 = signal.get('tp0', 0)
        tp1 = signal.get('tp1', 0)
        tp2 = signal.get('tp2', 0)
        confidence = signal.get('confidence', 0)
        hold_time = signal.get('expected_hold', 'Unknown')
        risk_details = signal.get('risk_details', {})
        
        # Calculate pips
        pip_divisor = 10000.0
        if "JPY" in symbol:
            pip_divisor = 100.0
        elif "GC" in symbol or "BTC" in symbol:
            pip_divisor = 10.0
            
        sl_pips = abs(entry - sl) * pip_divisor
        tp0_pips = abs(tp0 - entry) * pip_divisor
        tp1_pips = abs(tp1 - entry) * pip_divisor
        tp2_pips = abs(tp2 - entry) * pip_divisor
        
        # Session and Probability Formatting
        session_name = SessionFilter.get_session_name()
        quality_score = signal.get('quality_score', 0)
        is_high_prob = quality_score >= 8.0
        
        # Theme Determination (V17.0: Visual Intensity)
        is_swing = "H1" in signal.get('timeframe', '') or "swing" in signal.get('strategy_id', '').lower()
        
        if is_swing:
            # 💎 INSTITUTIONAL SWING THEME
            border = "█" * 45
            header_text = f"🏛️ INSTITUTIONAL SWING POSITION 🏛️"
            intensity_emoji = "💎💎💎"
            theme_color = "GOLD" # Conceptual
            main_icon = "🏆"
            bullet = "🧱"
        else:
            # ⚡ FLASH SCALP THEME
            border = "≈" * 60
            header_text = f"⚡ QUANT INTRADAY SCALP ⚡"
            intensity_emoji = "🏎️💨"
            theme_color = "BLUE" # Conceptual
            main_icon = "🏹"
            bullet = "•"

        session_emoji = "🇬🇧" if "London Open" in session_name else "🇺🇸" if "Overlap" in session_name else "🌐"
        prob_header = f"{intensity_emoji} HIGH PROBABILITY {intensity_emoji}" if is_high_prob else ""
        reasoning = SignalFormatter.generate_reasoning(signal)
        
        # Format output
        output = f"""
{border}
{main_icon} {direction} {header_text} {main_icon}
{border}
{prob_header}

{session_emoji} <b>MARKET CONTEXT:</b> {session_name}

📊 <b>TRADE SETUP</b>
{bullet} <b>Symbol:</b>       {symbol}
{bullet} <b>Direction:</b>    {direction} ({trade_type})
{bullet} <b>Timeframe:</b>    {signal.get('timeframe', 'N/A')}
{bullet} <b>Entry Price:</b>  {entry:.5f} {'(Limit Order)' if signal.get('is_limit_order') else '(Market Order)'}
{bullet} <b>Stop Loss:</b>    {sl:.5f} ({sl_pips:.1f} pips risk)

🎯 <b>PROFIT TARGETS</b>
1️⃣ <b>TP1 (Secure):</b> {tp0:.5f} (+{tp0_pips:.1f} pips)
2️⃣ <b>TP2 (Growth):</b> {tp1:.5f} (+{tp1_pips:.1f} pips)
3️⃣ <b>TP3 (Runner):</b> {tp2:.5f} (+{tp2_pips:.1f} pips)

📝 <b>STRATEGIC REASONING</b>
{reasoning}

🛡️ <b>RISK GUIDANCE</b>
{bullet} <b>Recommended Risk:</b> {risk_details.get('risk_percent', 0):.1f}% of balance
{bullet} <b>Position Size:</b>    {risk_details.get('lots', risk_details.get('lot_size', 0)):.2f} lots
{bullet} <b>Dollar Risk:</b>      ${risk_details.get('risk_cash', risk_details.get('risk_amount', 0)):.2f}
{bullet} <b>Expected Hold:</b>   ~{hold_time}

⚙️ <b>V23.0 ENGINE DETAILS</b>
{bullet} <b>Quality Score:</b> {quality_score:.1f}/10.0 {"🏆 INSTITUTIONAL QUALITY" if is_high_prob else "✅ QUANT VERIFIED"}
{border}
"""
        return output
    
    @staticmethod
    def format_personalized_signal(signal: dict, client: dict) -> str:
        """
        Formats a signal specifically for a single client with their balance.
        """
        from core.filters.risk_manager import RiskManager
        
        # Calculate personalized risk for this client
        p_risk = RiskManager.calculate_lot_size(
            signal.get('symbol', 'EURUSD'), 
            signal.get('entry_price', 0), 
            signal.get('sl', 0),
            balance=client.get('account_balance', 100),
            risk_pct_override=client.get('risk_percent', 2.0)
        )
        
        # Update signal with personalized risk for the basic formatter
        personal_signal = signal.copy()
        personal_signal['risk_details'] = p_risk
        
        # Add client-specific banner to the output
        base_output = SignalFormatter.format_signal(personal_signal)
        
        # Beginner-friendly personalization
        safety_check = "✅ <b>SAFE:</b> Risk is within healthy limits."
        if p_risk.get('is_high_risk'):
            safety_check = "⚠️ <b>CAUTION:</b> High risk for your account size. Consider reducing lot size."

        client_banner = f"""
👤 <b>YOUR PERSONAL PLAN</b>
💰 <b>Balance:</b> ${client['account_balance']:.2f}
📉 <b>Your Risk:</b> {p_risk.get('risk_percent', 0.0):.1f}%
🛡️ <b>Status:</b> {safety_check}
"""
        # Insert personalize banner before Risk Guidance
        parts = base_output.split("🛡️ <b>RISK GUIDANCE</b>")
        if len(parts) > 1:
            header = parts[0]
            rest = parts[1]
            return f"{header}{client_banner}\n🛡️ <b>RISK GUIDANCE</b>{rest}"
            
        return base_output

    @staticmethod
    def format_signal_json(signal: dict) -> dict:
        """
        Formats signal as structured JSON for API/Webhook integration.
        """
        return {
            'symbol': signal.get('symbol'),
            'direction': signal.get('direction'),
            'type': signal.get('trade_type'),
            'timeframe': signal.get('timeframe'),
            'entry': signal.get('entry_price'),
            'stop_loss': signal.get('sl'),
            'take_profits': {
                'tp0': {'price': signal.get('tp0'), 'size_pct': 50},
                'tp1': {'price': signal.get('tp1'), 'size_pct': 30},
                'tp2': {'price': signal.get('tp2'), 'size_pct': 20}
            },
            'position_size': signal.get('risk_details', {}).get('lots', signal.get('risk_details', {}).get('lot_size', 0)),
            'risk_usd': signal.get('risk_details', {}).get('risk_cash', signal.get('risk_details', {}).get('risk_amount', 0)),
            'confidence': signal.get('confidence'),
            'expected_hold': signal.get('expected_hold')
        }
