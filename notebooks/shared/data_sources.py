import os
import json
from datetime import datetime


def list_raw_csv(data_dir):
    if not os.path.isdir(data_dir):
        return []
    files = [f for f in os.listdir(data_dir) if f.startswith('raw_sensor_data_') and f.endswith('.csv')]
    files.sort(reverse=True)
    return files


def list_features_csv(data_dir):
    if not os.path.isdir(data_dir):
        return []
    files = []
    latest = os.path.join(data_dir, 'features_latest.csv')
    if os.path.exists(latest):
        files.append('features_latest.csv')
    extracted = [f for f in os.listdir(data_dir) if f.startswith('features_extracted_') and f.endswith('.csv')]
    extracted.sort(reverse=True)
    for f in extracted:
        if f not in files:
            files.append(f)
    return files


def _load_config(config_path, defaults=None):
    data = defaults.copy() if defaults else {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                data.update(json.load(f))
        except Exception:
            pass
    return data


def _save_config(config_path, data):
    try:
        with open(config_path, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def select_raw_source(data_dir, config_path, allow_sql=True, default_source='AUTO'):
    """Seleciona fonte de dados RAW (AUTO/SQL/CSV) e persiste a escolha.

    Retorna: (resolved_source, csv_file), onde resolved_source ∈ {'SQL', 'CSV'}.
    """
    valid_sources = ('AUTO', 'SQL', 'CSV')
    default_source = str(default_source or 'AUTO').upper()
    if default_source not in valid_sources:
        default_source = 'AUTO'

    cfg = _load_config(config_path, defaults={
        'data_source': default_source,
        'csv_file': None,
    })

    requested_source = str(cfg.get('data_source', default_source) or default_source).upper()
    if requested_source not in valid_sources:
        requested_source = default_source

    csv_files = list_raw_csv(data_dir)
    csv_file = cfg.get('csv_file')
    if csv_file not in csv_files:
        csv_file = csv_files[0] if csv_files else None

    metrics_dir = os.path.dirname(config_path) or '.'
    manifest_path = os.path.join(metrics_dir, 'eda_input_manifest.json')

    def _manifest_csv_candidate():
        if not os.path.exists(manifest_path):
            return None
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            if not isinstance(manifest, dict):
                return None
            raw_name = manifest.get('filename') or manifest.get('csv_path')
            if not raw_name:
                return None
            cand = os.path.basename(str(raw_name))
            return cand if cand in csv_files else None
        except Exception:
            return None

    def _resolve(source_req, selected_csv):
        source_req = str(source_req or '').upper()
        selected_csv = selected_csv if selected_csv in csv_files else (csv_files[0] if csv_files else None)
        manifest_csv = _manifest_csv_candidate()

        if source_req == 'AUTO':
            if manifest_csv:
                return 'CSV', manifest_csv, f'manifest:{manifest_csv}'
            if allow_sql:
                return 'SQL', None, 'sql_live'
            return 'CSV', selected_csv, f'csv_fallback:{selected_csv or "none"}'

        if source_req == 'SQL':
            if allow_sql:
                return 'SQL', None, 'sql_live'
            return 'CSV', selected_csv, f'sql_disabled_csv:{selected_csv or "none"}'

        # CSV
        return 'CSV', selected_csv, f'csv_selected:{selected_csv or "none"}'

    resolved_source, resolved_csv, resolution_reason = _resolve(requested_source, csv_file)

    def _persist():
        _save_config(config_path, {
            'data_source': requested_source,
            'resolved_source': resolved_source,
            'resolution_reason': resolution_reason,
            'csv_file': resolved_csv if resolved_source == 'CSV' else csv_file,
            'updated_at': datetime.now().strftime('%Y%m%d_%H%M%S'),
        })

    try:
        import ipywidgets as widgets
        from IPython.display import display, clear_output
        _has_widgets = True
    except Exception as e:
        _has_widgets = False
        print(f'[AVISO] ipywidgets nao disponivel: {e}')
        _persist()
        print(f'[INFO] Requested source: {requested_source}')
        print(f'[INFO] Resolved source:  {resolved_source}')
        if resolved_source == 'CSV':
            print(f'[INFO] CSV file:        {resolved_csv}')

    if _has_widgets:
        source_options = [('AUTO (recomendado)', 'AUTO')]
        if allow_sql:
            source_options.append(('SQL (nova coleta)', 'SQL'))
        source_options.append(('CSV (output/data)', 'CSV'))

        if not allow_sql and requested_source == 'SQL':
            requested_source = 'AUTO'
            resolved_source, resolved_csv, resolution_reason = _resolve(requested_source, csv_file)

        source_dropdown = widgets.Dropdown(
            options=source_options,
            value=requested_source,
            description='Fonte:',
            style={'description_width': 'initial'},
        )

        csv_options = csv_files if csv_files else ['<nenhum arquivo>']
        csv_dropdown = widgets.Dropdown(
            options=csv_options,
            value=csv_file if csv_file else (csv_options[0] if csv_options else '<nenhum arquivo>'),
            description='Arquivo:',
            style={'description_width': 'initial'},
        )
        csv_dropdown.disabled = (source_dropdown.value != 'CSV') or not csv_files

        out = widgets.Output()

        def _update_config(_=None):
            nonlocal requested_source, csv_file, resolved_source, resolved_csv, resolution_reason
            requested_source = str(source_dropdown.value or 'AUTO').upper()
            selected_csv = csv_dropdown.value if csv_dropdown.value != '<nenhum arquivo>' else None
            if selected_csv in csv_files:
                csv_file = selected_csv
            resolved_source, resolved_csv, resolution_reason = _resolve(requested_source, csv_file)
            _persist()
            with out:
                clear_output()
                print(f'Fonte solicitada: {requested_source}')
                print(f'Fonte resolvida:  {resolved_source}')
                print(f'Regra:            {resolution_reason}')
                if resolved_source == 'CSV':
                    if resolved_csv:
                        print(f'Arquivo CSV:      {resolved_csv}')
                    else:
                        print('Arquivo CSV:      <nenhum arquivo>')
                print(f'Config salvo em:  {config_path}')

        def _on_source_change(change):
            if change.get('name') == 'value':
                csv_dropdown.disabled = (change.get('new') != 'CSV') or not csv_files
                _update_config()

        def _on_csv_change(change):
            if change.get('name') == 'value':
                _update_config()

        source_dropdown.observe(_on_source_change, names='value')
        csv_dropdown.observe(_on_csv_change, names='value')

        display(widgets.VBox([source_dropdown, csv_dropdown, out]))
        _update_config()

    return resolved_source, resolved_csv if resolved_source == 'CSV' else None


def select_features_csv(data_dir, config_path, eda_run_config_path=None):
    """Seleciona CSV de features e persiste a escolha.

    Retorna: features_csv_file
    """
    features_csv_file = None

    cfg = _load_config(config_path, defaults={'features_csv_file': None})
    if cfg.get('features_csv_file'):
        features_csv_file = os.path.basename(cfg.get('features_csv_file'))

    if not features_csv_file and eda_run_config_path and os.path.exists(eda_run_config_path):
        try:
            with open(eda_run_config_path, 'r') as f:
                eda_cfg = json.load(f)
            feat_latest = eda_cfg.get('features_latest_path')
            feat_path = eda_cfg.get('features_csv_path')
            if feat_latest:
                features_csv_file = os.path.basename(feat_latest)
            elif feat_path:
                features_csv_file = os.path.basename(feat_path)
        except Exception:
            pass

    feature_files = list_features_csv(data_dir)
    if features_csv_file not in feature_files:
        features_csv_file = feature_files[0] if feature_files else None

    def _persist():
        _save_config(config_path, {
            'features_csv_file': features_csv_file,
            'updated_at': datetime.now().strftime('%Y%m%d_%H%M%S'),
        })

    try:
        import ipywidgets as widgets
        from IPython.display import display, clear_output
        _has_widgets = True
    except Exception as e:
        _has_widgets = False
        print(f'[AVISO] ipywidgets nao disponivel: {e}')
        _persist()
        print(f'[INFO] Usando padroes: FEATURES_CSV_FILE={features_csv_file}')

    if _has_widgets:
        feat_options = feature_files if feature_files else ['<nenhum arquivo>']
        features_dropdown = widgets.Dropdown(
            options=feat_options,
            value=features_csv_file if features_csv_file else (feat_options[0] if feat_options else '<nenhum arquivo>'),
            description='Features CSV:',
            style={'description_width': 'initial'},
        )

        refresh_button = widgets.Button(description='Atualizar lista')
        out = widgets.Output()

        def _update_config(_=None):
            nonlocal features_csv_file
            features_csv_file = features_dropdown.value if features_dropdown.value != '<nenhum arquivo>' else None
            _persist()
            with out:
                clear_output()
                print(f'Features CSV: {features_csv_file}')
                if features_csv_file and features_csv_file != '<nenhum arquivo>':
                    _summarize_csv(os.path.join(data_dir, features_csv_file))
                print(f'Config salvo em: {config_path}')

        def _refresh_lists(_):
            nonlocal feature_files
            feature_files = list_features_csv(data_dir)
            new_feat = feature_files if feature_files else ['<nenhum arquivo>']
            features_dropdown.options = new_feat
            if features_csv_file in new_feat:
                features_dropdown.value = features_csv_file
            else:
                features_dropdown.value = new_feat[0]
            _update_config()
            with out:
                print('Listas atualizadas.')

        def _summarize_csv(path):
            try:
                import pandas as pd
                df_cols = pd.read_csv(path, nrows=0)
                cols = df_cols.columns.tolist()
                rows = None
                classes = None
                if 'fan_state' in cols:
                    df_state = pd.read_csv(path, usecols=['fan_state'])
                    rows = len(df_state)
                    classes = df_state['fan_state'].value_counts().to_dict()
                else:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        rows = sum(1 for _ in f) - 1
                print(f'Shape: ({rows}, {len(cols)})')
                print(f'Colunas: {cols}')
                if classes is not None:
                    print(f'Classes: {classes}')
            except Exception as e:
                print(f'Nao foi possivel resumir CSV: {e}')

        features_dropdown.observe(lambda change: _update_config() if change.get('name') == 'value' else None, names='value')
        refresh_button.on_click(_refresh_lists)

        display(widgets.VBox([features_dropdown, refresh_button, out]))
        _update_config()

    return features_csv_file


def load_raw_from_oracle(
    connection_str,
    device_id=None,
    collection_id=None,
    limit=0,
    table="sensor_training_data",
):
    """Carrega dados raw do Oracle em formato compativel com notebooks.

    Usa sensor_training_data por padrao (coletas supervisionadas).
    Para dados legados use table='sensor_data'.
    Requer pandas + sqlalchemy + python-oracledb.
    """
    import pandas as pd
    from sqlalchemy import create_engine, text

    sql = f"""
        SELECT
            id,
            ts_epoch AS timestamp,
            temperature,
            vibration,
            accel_x_g,
            accel_y_g,
            accel_z_g,
            gyro_x_dps,
            gyro_y_dps,
            gyro_z_dps,
            sample_rate,
            fan_state,
            collection_id,
            cmd_speed_label,
            rot_state_label,
            use_state_label,
            vib_profile_label,
            label_source,
            transition_marker,
            device_id,
            created_at
        FROM {table}
        WHERE 1=1
    """
    params = {}
    if device_id:
        sql += " AND device_id = :device_id"
        params["device_id"] = device_id
    if collection_id:
        sql += " AND collection_id = :collection_id"
        params["collection_id"] = collection_id
    sql += " ORDER BY ts_epoch ASC"

    if limit and int(limit) > 0:
        sql = f"SELECT * FROM ({sql}) WHERE ROWNUM <= :lim"
        params["lim"] = int(limit)

    engine = create_engine(connection_str)
    with engine.connect() as conn:
        df = pd.read_sql(text(sql), conn, params=params)

    if not df.empty and "timestamp" in df.columns:
        df["timestamp_iso"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )

    return df
