import streamlit as st
import re
import requests
from urllib.parse import quote, urlparse
from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import unicodedata

# Configuração da página do Streamlit
st.set_page_config(page_title="Testar Xtream API", layout="centered")

# Estilos CSS para ajustar o layout e o comportamento de quebra de linha
st.markdown("""
    <style>
        .block-container {
            padding-top: 2.5rem;
        }
        .stCodeBlock, code {
            white-space: pre-wrap !important;
            word-break: break-all !important;
        }
        a {
            word-break: break-all !important;
        }
    </style>
""", unsafe_allow_html=True)

# Título e descrição da página
st.markdown("""
    <h5 style='margin-bottom: 0.1rem;'>🔌 Testar Xtream API</h5>
    <p style='margin-top: 0.1rem;'>
        ✅ <strong>Domínios aceitos no Smarters Pro:</strong> <code>.ca</code>, <code>.io</code>, <code>.cc</code>, <code>.me</code>, <code>.top</code>, <code>.space</code>, <code>.in</code>.<br>
        ❌ <strong>Domínios não aceitos:</strong> <code>.site</code>, <code>.com</code>, <code>.lat</code>, <code>.live</code>, <code>.icu</code>, <code>.xyz</code>, <code>.online</code>.
    </p>
""", unsafe_allow_html=True)

# Inicializa o estado da sessão para o campo de texto e pesquisa
if "m3u_input_value" not in st.session_state:
    st.session_state.m3u_input_value = ""

if "search_name" not in st.session_state:
    st.session_state.search_name = ""

def clear_input():
    """Limpa o campo de texto e re-define o estado do formulário."""
    st.session_state.m3u_input_value = ""
    st.session_state.search_name = ""
    st.session_state.form_submitted = False

def normalize_text(text):
    """Normaliza o texto, removendo acentos, cedilha e convertendo para minúsculas."""
    if not isinstance(text, str):
        return ""
    text = text.lower()
    normalized = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    return normalized

def parse_urls(message):
    """Extrai URLs M3U e Player API da mensagem de texto, evitando duplicatas."""
    m3u_pattern = r"(https?://[^\s]+?get\.php\?username=[^\s&]+&password=[^\s&]+&type=m3u_plus(?:&output=[^\s]+)?)"
    api_pattern = r"(https?://[^\s]+?player_api\.php\?username=[^\s&]+&password=[^\s&]+)"
    urls = re.findall(m3u_pattern, message) + re.findall(api_pattern, message)

    parsed_urls = []
    unique_urls = set()

    for url in urls:
        current_url = url[0] if isinstance(url, tuple) else url

        base_match = re.search(r"(https?://[^/]+(?::\d+)?)", current_url)
        user_match = re.search(r"username=([^&]+)", current_url)
        pwd_match = re.search(r"password=([^&]+)", current_url)

        if base_match and user_match and pwd_match:
            base = base_match.group(1).replace("https://", "http://")
            username = user_match.group(1)
            password = pwd_match.group(1)

            identifier = (base, username, password)
            if identifier not in unique_urls:
                unique_urls.add(identifier)
                parsed_urls.append({
                    "url": current_url,
                    "base": base,
                    "username": username,
                    "password": password
                })
    return parsed_urls

def get_series_details(base_url, username, password, series_id):
    """
    Busca informações detalhadas de uma série, incluindo o número de temporadas
    e o último episódio.
    """
    try:
        series_info_url = f"{base_url}/player_api.php?username={quote(username)}&password={quote(password)}&action=get_series_info&series_id={series_id}"
        response = requests.get(series_info_url, timeout=10)
        response.raise_for_status()
        series_data = response.json()

        if not series_data or "episodes" not in series_data:
            return None

        episodes_by_season = series_data.get("episodes", {})

        # Encontra a última temporada
        latest_season_number = max(
            int(season_num) for season_num in episodes_by_season.keys() if season_num.isdigit()
        )
        latest_season = episodes_by_season.get(str(latest_season_number), [])

        # Encontra o último episódio da última temporada
        if latest_season:
            latest_episode = latest_season[-1]
            title = latest_episode.get("title", "")

            # Tenta extrair SXXEXX com regex
            match = re.search(r"S(\d+)E(\d+)", title, re.IGNORECASE)
            if match:
                s_e_string = match.group(0).upper()
            else:
                s_e_string = f"S{latest_season_number:02d}E{len(latest_season):02d}"

            return s_e_string

    except (requests.exceptions.RequestException, ValueError, KeyError):
        return None
    return None

def get_xtream_info(parsed_url_data, search_name=None):
    """
    Função wrapper para testar uma única URL. Retorna os dados originais e os resultados.
    """
    base = parsed_url_data["base"]
    username = parsed_url_data["username"]
    password = parsed_url_data["password"]

    username_encoded = quote(username)
    password_encoded = quote(password)
    api_url = f"{base}/player_api.php?username={username_encoded}&password={password_encoded}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Connection": "close"
    }

    result = {
        "is_json": False, "real_server": base, "exp_date": "Falha no login",
        "active_cons": "N/A", "max_connections": "N/A", "has_adult_content": False,
        "is_accepted_domain": False, "live_count": 0, "vod_count": 0, "series_count": 0,
        "search_matches": {} # Alterado para um dicionário para armazenar por categoria
    }

    try:
        response = requests.get(api_url, headers=headers, timeout=10, allow_redirects=True)
        response.raise_for_status()
        json_data = response.json()

        if not json_data or "user_info" not in json_data:
             return parsed_url_data, result

        result["is_json"] = True
        user_info = json_data.get("user_info", {})
        server_info = json_data.get("server_info", {})

        real_server_url = server_info.get("url", base)
        if not real_server_url.startswith(("http://", "https://")):
            real_server_url = "http://" + real_server_url
        result["real_server"] = real_server_url.replace("https://", "http://").rstrip("/")

        valid_tlds = ('.ca', '.io', '.cc', '.me', '.in')
        domain = urlparse(result["real_server"]).netloc
        result["is_accepted_domain"] = any(domain.lower().endswith(tld) for tld in valid_tlds)

        exp_date_ts = user_info.get("exp_date")
        if exp_date_ts and str(exp_date_ts).isdigit():
            result["exp_date"] = "Nunca expira" if int(exp_date_ts) > time.time() * 2 else datetime.fromtimestamp(int(exp_date_ts)).strftime('%d/%m/%Y')
        else:
            result["exp_date"] = "N/A"

        result["active_cons"] = user_info.get("active_cons", "N/A")
        result["max_connections"] = user_info.get("max_connections", "N/A")

        api_base_url = f"{result['real_server']}/player_api.php?username={username_encoded}&password={password_encoded}"
        adult_keywords = ["adulto", "adultos", "xxx", "+18"]

        with ThreadPoolExecutor(max_workers=3) as cat_executor:
            actions = ["get_live_categories", "get_vod_categories", "get_series_categories"]
            futures = {cat_executor.submit(lambda: requests.get(f"{api_base_url}&action={a}", headers=headers, timeout=15).json()): a for a in actions}
            for future in as_completed(futures):
                try:
                    categories = future.result()
                    if categories and any(keyword in normalize_text(cat.get("category_name", "")) for cat in categories for keyword in adult_keywords):
                        result["has_adult_content"] = True
                        break
                except:
                    continue

        with ThreadPoolExecutor(max_workers=3) as count_executor:
            actions = {"live": "get_live_streams", "vod": "get_vod_streams", "series": "get_series"}
            futures = {count_executor.submit(lambda: requests.get(f"{api_base_url}&action={a}", headers=headers, timeout=15).json()): k for k, a in actions.items()}

            if search_name:
                normalized_search = normalize_text(search_name)
                result["search_matches"] = {"Canais": [], "Filmes": [], "Séries": {}} # Inicializa as listas de cada categoria

            for future in as_completed(futures):
                key = futures[future]
                try:
                    data = future.result()
                    result[f"{key}_count"] = len(data) if data else 0
                    if search_name and data:
                        if key == "series":
                            # Processamento especial para séries
                            series_matches = [
                                item for item in data if normalized_search in normalize_text(item.get("name", ""))
                            ]
                            for series in series_matches:
                                series_id = series.get("series_id")
                                series_name = series.get("name")
                                # Aqui a nova função é chamada
                                s_e = get_series_details(result['real_server'], username, password, series_id)

                                if s_e:
                                    result["search_matches"]["Séries"][series_name] = s_e
                                else:
                                    result["search_matches"]["Séries"][series_name] = "N/A"
                        else:
                            matches = [item["name"] for item in data if normalized_search in normalize_text(item.get("name", ""))]
                            if matches:
                                if key == "live":
                                    result["search_matches"]["Canais"].extend(matches)
                                elif key == "vod":
                                    result["search_matches"]["Filmes"].extend(matches)
                except:
                    continue

        return parsed_url_data, result

    except (requests.exceptions.RequestException, ValueError):
        return parsed_url_data, result


# Criação do formulário na interface
with st.form(key="m3u_form"):
    m3u_message = st.text_area("Cole a mensagem com URLs M3U ou Player API", key="m3u_input_value", height=200)
    search_name = st.text_input("🔍 Buscar canal, filme ou série (opcional)", key="search_name")

    col1, col2 = st.columns([1,1])
    with col1:
        submit_button = st.form_submit_button("🚀 Testar APIs (Rápido)")
    with col2:
        clear_button = st.form_submit_button("🧹 Limpar", on_click=clear_input)

    if submit_button or st.session_state.get("form_submitted", False):
        if not m3u_message:
            st.warning("⚠️ Por favor, insira uma mensagem com URLs.")
        else:
            with st.spinner("Analisando APIs em paralelo... Isso será rápido!"):
                parsed_urls = parse_urls(m3u_message)

                if not parsed_urls:
                    st.warning("⚠️ Nenhuma URL válida encontrada na mensagem.")
                else:
                    results = []
                    with ThreadPoolExecutor(max_workers=10) as executor:
                        future_to_url = {executor.submit(get_xtream_info, url_data, search_name): url_data for url_data in parsed_urls}
                        for future in as_completed(future_to_url):
                            original_data, api_result = future.result()
                            api_url = f"{original_data['base']}/player_api.php?username={quote(original_data['username'])}&password={quote(original_data['password'])}"

                            results.append({
                                "api_url": api_url,
                                "username": original_data["username"],
                                "password": original_data["password"],
                                **api_result
                            })

                    results.sort(key=lambda item: item['is_json'], reverse=True)

                    st.markdown("---")
                    st.markdown("#### Resultados")

                    if not results:
                        st.info("Nenhuma URL foi processada.")
                    else:
                        for result in results:
                            status = "✅" if result["is_json"] else "❌"

                            st.markdown(
                                f"**{status} API URL:** <a href='{result['api_url']}' target='_blank'>{result['api_url']}</a>",
                                unsafe_allow_html=True
                            )

                            with st.container(border=True):
                                adult_emoji = "🔞 Contém" if result['has_adult_content'] else "✅ Não Contém"
                                domain_emoji = "✅ Sim" if result['is_accepted_domain'] else "❌ Não"
                                st.markdown(f"""
                                - **Usuário:** `{result['username']}`
                                - **Senha:** `{result['password']}`
                                - **URL Real:** `{result['real_server']}`
                                - **Expira em:** `{result['exp_date']}`
                                - **Conexões:** `{result['active_cons']}` / `{result['max_connections']}`
                                - **Domínio Aceito na TV:** {domain_emoji}
                                - **Conteúdo Adulto:** {adult_emoji}
                                - **Canais:** `{result['live_count']}`
                                - **Filmes:** `{result['vod_count']}`
                                - **Séries:** `{result['series_count']}`
                                """)
                                # Exibição dos resultados por subcategoria
                                if search_name:
                                    if any(result["search_matches"].values()):
                                        st.markdown("**🔎 Resultados encontrados:**")
                                        for category, matches in result["search_matches"].items():
                                            if matches:
                                                st.markdown(f"**{category}:**")
                                                # Cria uma lista de strings formatadas e une com quebras de linha
                                                if category == "Séries":
                                                    series_list = []
                                                    for series_name, s_e_info in matches.items():
                                                        if s_e_info != "N/A":
                                                            series_list.append(f"- **{series_name}** ({s_e_info})")
                                                        else:
                                                            series_list.append(f"- **{series_name}** (Detalhes não disponíveis)")
                                                    st.markdown("\n".join(series_list))
                                                else:
                                                    # Já estava correto, mantido para consistência
                                                    matches_text = "\n".join([f"- {match}" for match in matches])
                                                    st.markdown(matches_text)
                            st.markdown("---")

if st.session_state.m3u_input_value:
    st.session_state.form_submitted = True
else:
    st.session_state.form_submitted = False
