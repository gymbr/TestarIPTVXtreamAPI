import streamlit as st
import re
import requests
from urllib.parse import quote, urlparse
from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import unicodedata
import urllib3

# Desabilitar avisos de segurança para certificados SSL inválidos (comum em IPTV)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuração da página do Streamlit
st.set_page_config(page_title="Testar Xtream API", layout="centered")

# Cabeçalhos para simular um navegador (Evita bloqueio do servidor)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Connection": "keep-alive"
}

# Estilos CSS
st.markdown("""
    <style>
        .block-container { padding-top: 2.5rem; }
        .stCodeBlock, code { white-space: pre-wrap !important; word-break: break-all !important; }
        a { word-break: break-all !important; }
    </style>
""", unsafe_allow_html=True)

st.markdown("""
    <h5 style='margin-bottom: 0.1rem;'>🔌 Testar Xtream API</h5>
    <p style='margin-top: 0.1rem;'>
        ✅ <strong>Domínios aceitos no Smarters Pro:</strong> <code>.ca</code>, <code>.io</code>, <code>.cc</code>, <code>.me</code>, <code>.top</code>, <code>.space</code>, <code>.in</code>.<br>
        ❌ <strong>Domínios não aceitos:</strong> <code>.site</code>, <code>.com</code>, <code>.lat</code>, <code>.live</code>, <code>.icu</code>, <code>.xyz</code>, <code>.online</code>.
    </p>
""", unsafe_allow_html=True)

if "m3u_input_value" not in st.session_state:
    st.session_state.m3u_input_value = ""
if "search_name" not in st.session_state:
    st.session_state.search_name = ""

def clear_input():
    st.session_state.m3u_input_value = ""
    st.session_state.search_name = ""

def normalize_text(text):
    if not isinstance(text, str): return ""
    text = text.lower()
    return unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')

def parse_urls(message):
    m3u_pattern = r"(https?://[^\s\"']+(?:get\.php|player_api\.php)\?username=([a-zA-Z0-9]+)&password=([a-zA-Z0-9]+))"
    found = re.findall(m3u_pattern, message)
    parsed_urls = []
    unique_ids = set()

    for item in found:
        full_url, user, pwd = item
        # Extrai a base URL incluindo a porta para a conexão técnica
        base_match = re.search(r"(https?://[^/]+(?::\d+)?)", full_url)
        if base_match:
            base_full = base_match.group(1)
            if base_full.endswith('/'): base_full = base_full[:-1]
            
            # Criar a versão sem porta para exibição no layout
            parsed_url = urlparse(base_full)
            # Remove a porta do netloc (ex: pro123.ddns.me:80 -> pro123.ddns.me)
            base_display = f"{parsed_url.scheme}://{parsed_url.hostname}"
            
            identifier = (base_full, user, pwd)
            if identifier not in unique_ids:
                unique_ids.add(identifier)
                parsed_urls.append({
                    "base": base_full, 
                    "display_base": base_display, 
                    "username": user, 
                    "password": pwd
                })
    return parsed_urls

def get_series_details(base_url, username, password, series_id):
    try:
        url = f"{base_url}/player_api.php?username={quote(username)}&password={quote(password)}&action=get_series_info&series_id={series_id}"
        resp = requests.get(url, headers=HEADERS, verify=False, timeout=10).json()
        episodes = resp.get("episodes", {})
        if not episodes: return None
        last_season_num = max(int(k) for k in episodes.keys() if k.isdigit())
        last_episode = episodes[str(last_season_num)][-1]
        title = last_episode.get("title", "")
        match = re.search(r"S(\d+)E(\d+)", title, re.IGNORECASE)
        return match.group(0).upper() if match else f"S{last_season_num:02d}E{len(episodes[str(last_season_num)]):02d}"
    except: return None

def get_xtream_info(url_data, search_name=None):
    base, user, pwd = url_data["base"], url_data["username"], url_data["password"]
    u_enc, p_enc = quote(user), quote(pwd)
    api_url = f"{base}/player_api.php?username={u_enc}&password={p_enc}"
    
    res = {
        "is_json": False, "real_server": base, "exp_date": "Falha no login",
        "active_cons": "N/A", "max_connections": "N/A", "has_adult_content": False,
        "is_accepted_domain": False, "live_count": 0, "vod_count": 0, "series_count": 0,
        "search_matches": {"Canais": [], "Filmes": [], "Séries": {}}
    }

    adult_keys = ["adult", "xxx", "+18", "sex", "porn", "adulto"]

    try:
        main_resp = requests.get(api_url, headers=HEADERS, verify=False, timeout=15)
        try:
            data_json = main_resp.json()
        except:
            return url_data, res

        if "user_info" not in data_json: 
            return url_data, res
        
        res["is_json"] = True
        user_info = data_json.get("user_info", {})
        exp = user_info.get("exp_date")
        if exp and str(exp).isdigit():
            if int(exp) == 0:
                res["exp_date"] = "Ilimitado"
            else:
                res["exp_date"] = "Nunca expira" if int(exp) > time.time() * 200 else datetime.fromtimestamp(int(exp)).strftime('%d/%m/%Y')
        else:
             res["exp_date"] = "Indefinido"
        
        res["active_cons"] = user_info.get("active_cons", "0")
        res["max_connections"] = user_info.get("max_connections", "0")
        
        valid_tlds = ('.ca', '.io', '.cc', '.me', '.in', '.top', '.space')
        domain = urlparse(base).netloc.lower()
        res["is_accepted_domain"] = any(domain.endswith(tld) for tld in valid_tlds)

        try:
            cat_resp = requests.get(f"{api_url}&action=get_live_categories", headers=HEADERS, verify=False, timeout=10).json()
            if isinstance(cat_resp, list):
                for cat in cat_resp:
                    cat_name = normalize_text(cat.get("category_name", ""))
                    if any(key in cat_name for key in adult_keys):
                        res["has_adult_content"] = True
                        break
        except: pass

        actions = {"live": "get_live_streams", "vod": "get_vod_streams", "series": "get_series"}
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_key = {
                executor.submit(requests.get, f"{api_url}&action={act}", headers=HEADERS, verify=False, timeout=20): key 
                for key, act in actions.items()
            }
            for future in as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    resp_content = future.result().json()
                    if isinstance(resp_content, list):
                        res[f"{key}_count"] = len(resp_content)
                        
                        if not res["has_adult_content"] and key == "live":
                            for item in resp_content[:100]:
                                if any(key in normalize_text(item.get("name", "")) for key in adult_keys):
                                    res["has_adult_content"] = True
                                    break

                        if search_name:
                            s_norm = normalize_text(search_name)
                            if key == "series":
                                for item in resp_content:
                                    if s_norm in normalize_text(item.get("name")):
                                        s_id = item.get("series_id")
                                        s_info = get_series_details(base, user, pwd, s_id)
                                        res["search_matches"]["Séries"][item.get("name")] = s_info or "Disponível"
                            else:
                                matches = [i.get("name") for i in resp_content if s_norm in normalize_text(i.get("name"))]
                                cat_name = "Canais" if key == "live" else "Filmes"
                                res["search_matches"][cat_name].extend(matches)
                except: continue
    except: pass
    return url_data, res

# Interface
with st.form(key="m3u_form"):
    m3u_message = st.text_area("Cole o texto contendo as URLs aqui", key="m3u_input_value", height=150)
    search_query = st.text_input("🔍 Buscar conteúdo específico (opcional)", key="search_name")
    
    c1, c2 = st.columns([1,1])
    with c1: submit = st.form_submit_button("🚀 Testar Agora")
    with c2: clear = st.form_submit_button("🧹 Limpar", on_click=clear_input)

if submit and m3u_message:
    parsed = parse_urls(m3u_message)
    if not parsed:
        st.error("Nenhuma URL ou credencial válida encontrada no texto.")
    else:
        with st.spinner(f"Analisando {len(parsed)} servidor(es)..."):
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(get_xtream_info, url, search_query) for url in parsed]
                for future in as_completed(futures):
                    orig, info = future.result()
                    
                    status_icon = "✅" if info["is_json"] else "❌"
                    
                    with st.container(border=True):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            # Usa 'display_base' para mostrar o servidor SEM a porta
                            st.write(f"{status_icon} **Servidor:** `{orig['display_base']}`")
                            st.write(f"👤 **Usuário:** `{orig['username']}`")
                            st.write(f"🔑 **Senha:** `{orig['password']}`")
                            
                            exp_date = info['exp_date']
                            color_date = "red" if "Falha" in exp_date else "green"
                            st.markdown(f"📅 **Expira:** <span style='color:{color_date}'>**{exp_date}**</span>", unsafe_allow_html=True)
                            
                            adult_status = "🔞 Sim" if info["has_adult_content"] else "🛡️ Não"
                            st.write(f"🔞 **Adulto:** `{adult_status}`")
                            
                        with col_b:
                            st.write(f"📺 **Canais:** `{info['live_count']}`")
                            st.write(f"🎬 **Filmes:** `{info['vod_count']}`")
                            st.write(f"🍿 **Séries:** `{info['series_count']}`")
                            st.write(f"👥 **Conexões:** `{info['active_cons']}/{info['max_connections']}`")
                            st.write(f"🌐 **Domínio OK:** {'✅' if info['is_accepted_domain'] else '❌'}")

                        if search_query and any(info["search_matches"].values()):
                            st.info(f"🔎 Resultados para '{search_query}':")
                            for cat, matches in info["search_matches"].items():
                                if matches:
                                    st.write(f"**{cat}:**")
                                    if isinstance(matches, dict):
                                        for n, v in matches.items(): st.write(f"- {n} ({v})")
                                    else:
                                        for m in matches[:10]: st.write(f"- {m}")
                                        if len(matches) > 10: st.write(f"... e mais {len(matches)-10}")
                    st.divider()

st.info("Nota: Este script usa Headers de navegador e ignora erros SSL para garantir conexão com servidores antigos ou mal configurados.")
