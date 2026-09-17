import streamlit as st
import pandas as pd
from scanner import scan_watchlist
from config import WATCHLIST

st.set_page_config(page_title="Global Stock Signal Bot", page_icon="📈", layout="wide")

st.title("🌍 Global Stock Signal Bot")
st.caption("50 global stocks • LONG / SHORT • €500 ×3 • TP/SL ±€20")

c1, c2, c3 = st.columns(3)
c1.metric("Watchlist", "50")
c2.metric("Stake", "€500")
c3.metric("Leverage", "×3")

if st.button("🔎 CHECK 50 MÃ", type="primary", use_container_width=True):
    with st.spinner("Đang quét 50 mã..."):
        results = scan_watchlist(WATCHLIST)
    st.session_state["results"] = results
    st.session_state["checked_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

if "results" in st.session_state:
    results = st.session_state["results"]
    st.divider()
    st.subheader("📡 Signals")

    if not results:
        st.warning("KHÔNG CÓ")
    else:
        for r in results:
            line = (
                f"{'🟢' if r['direction']=='LONG' else '🔴'} "
                f"**{r['direction']} {r['symbol']}** — "
                f"Entry {r['entry']:.2f} — TP {r['tp']:.2f} — SL {r['sl']:.2f} — "
                f"Score {r['score']}/6"
            )
            st.markdown(line)

        st.divider()
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

    st.caption(f"Last check: {st.session_state.get('checked_at','')}")

with st.expander("50 mã đang quét"):
    st.write(", ".join(WATCHLIST))
