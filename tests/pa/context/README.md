# Testes — `pa/context`

Testes determinísticos da Context Layer do PA. Nenhum dos testes usa LLM
real ou filesystem real — o LLM é mockado com `MagicMock` e o disco usa a
fixture `tmp_path` do pytest.

| Arquivo | Alvo | Nº de testes |
|---|---|---|
| [test_conversation.py](test_conversation.py) | `ConversationHistory` ([src/axon/pa/context/conversation.py](../../../src/axon/pa/context/conversation.py)) | 34 |
| [test_memory.py](test_memory.py) | `MemoryBank` ([src/axon/pa/context/memory.py](../../../src/axon/pa/context/memory.py)) | 34 |

Rodar:

```bash
pytest tests/pa/context/
```

---

## test_conversation.py

Cobre o histórico de uma sessão entre usuário e PA: sliding window,
sumarização do overflow via LLM, formatação do contexto e persistência.

**Fixtures**

- `config_small` — `ConversationConfig` com janela de 3 mensagens, para
  facilitar testes de overflow.
- `config_default` — `ConversationConfig` padrão.
- `empty_history` — `ConversationHistory` recém-criado, sem mensagens.
- `history_with_messages` — histórico já com um turno user/assistant.

### `add_message`
- `test_add_message_appends_turn` — mensagem adicionada vira um turno.
- `test_add_message_preserves_order` — ordem de inserção é mantida.
- `test_add_message_updates_timestamp` — `updated_at` avança a cada mensagem.

### Sliding window
- `test_window_not_exceeded_below_limit` — exatamente no limite não corta.
- `test_window_trims_when_exceeded` — overflow mantém só as N últimas.
- `test_window_keeps_most_recent` — após várias mensagens, sobram as mais recentes.

### Sumarização no overflow
- `test_summarization_called_when_overflow` — com `llm_client`, o overflow dispara o summarizer.
- `test_summarization_receives_overflow_messages` — o summarizer recebe exatamente os turnos que saíram da janela.
- `test_summarization_accumulates_existing_summary` — o summary anterior é passado para o próximo ciclo (contexto nunca é perdido por completo).
- `test_overflow_without_summarizer_discards_messages` — sem `llm_client`, o overflow é descartado e o summary não muda.
- `test_summarizer_fallback_on_llm_error` — se o LLM falha, o summary anterior é preservado.

### `get_context` / `get_context_str`
- `test_get_context_returns_openai_format` — retorna lista no formato OpenAI Chat (`role`/`content`).
- `test_get_context_includes_all_messages` — todas as mensagens da janela aparecem.
- `test_get_context_empty_without_summary` — histórico vazio retorna `[]`.
- `test_get_context_includes_summary_when_present` — o summary entra como mensagem `system`.
- `test_summary_prepended_before_messages` — o summary vem antes das mensagens.
- `test_get_context_str_returns_string` — versão texto plano retorna `str`.
- `test_get_context_str_empty_returns_no_history` — vazio retorna `"No previous conversation."`.
- `test_get_context_str_includes_summary` — a versão texto inclui o summary.

### Helpers
- `test_is_empty_true_when_new` / `test_is_empty_false_after_message` — `is_empty()` reflete a presença de mensagens.
- `test_is_empty_false_with_summary_only` — só o summary já torna o histórico não-vazio.
- `test_last_user_message_returns_most_recent` — retorna a última mensagem do usuário.
- `test_last_user_message_returns_none_when_empty` — retorna `None` sem mensagens.

### Persistência
- `test_persist_creates_file` — `persist()` cria `{session_id}.json`.
- `test_persist_file_contains_valid_json` — o arquivo gravado é JSON válido com os campos esperados.
- `test_persist_creates_directory_if_missing` — diretórios intermediários são criados.
- `test_load_returns_same_data` — `load_or_create()` recarrega mensagens e summary.
- `test_load_or_create_returns_new_when_not_found` — sessão inexistente gera um histórico novo.
- `test_load_or_create_returns_empty_when_not_found` — histórico novo começa vazio.
- `test_load_or_create_loads_existing` — sessão existente é carregada do disco.
- `test_load_or_create_generates_uuid_when_session_id_none` — `session_id=None` gera um UUID.
- `test_load_or_create_updates_config_on_load` — o config atual sobrescreve o config salvo na sessão.
- `test_persist_and_reload_roundtrip` — roundtrip completo preserva todos os dados.

---

## test_memory.py

Cobre o `MemoryBank`: preferências e defaults do domínio que persistem
entre sessões (`preferred_format`, `language`, etc.).

### `set` / `get`
- `test_set_and_get_value` — valor gravado é recuperado.
- `test_get_returns_default_when_missing` — chave ausente retorna `None` ou o default informado.
- `test_set_overwrites_existing_key` — `set()` na mesma chave substitui sem duplicar entrada.
- `test_set_multiple_keys` — várias chaves coexistem.
- `test_set_updates_timestamp_on_overwrite` — overwrite atualiza o `updated_at` da entrada.
- `test_set_updates_bank_timestamp` — `set()` atualiza o `updated_at` do banco.
- `test_set_preserves_source` — o `source` informado é mantido.
- `test_set_default_source_is_operator` — `source` padrão é `"operator"`.
- `test_set_supports_bool_value` / `test_set_supports_int_value` / `test_set_supports_list_value` — valores não-string (bool, int, list) são suportados.

### `delete` / `clear` / `keys` / `is_empty`
- `test_delete_existing_key` — remove a entrada e retorna `True`.
- `test_delete_nonexistent_key_returns_false` — chave ausente retorna `False`.
- `test_delete_updates_timestamp` — `delete()` atualiza o `updated_at`.
- `test_clear_removes_all_entries` — `clear()` esvazia o banco.
- `test_keys_returns_all_keys` — `keys()` lista todas as chaves.
- `test_is_empty_true_when_new` / `test_is_empty_false_after_set` / `test_is_empty_true_after_clear` — `is_empty()` reflete o estado do banco.

### `get_summary`
- `test_get_summary_formats_correctly` — formata `key: value` por entrada.
- `test_get_summary_each_entry_on_own_line` — uma entrada por linha.
- `test_get_summary_prefixes_with_dash` — cada linha começa com `- `.
- `test_empty_memory_returns_no_memory_message` — banco vazio retorna `"No user memory available."`.
- `test_get_summary_after_clear_returns_empty_message` — idem após `clear()`.
- `test_get_summary_includes_bool_value` — valores bool aparecem no resumo.

### `persist` / `load`
- `test_persist_creates_file` — `persist()` grava o arquivo.
- `test_persist_creates_parent_directories` — diretórios intermediários são criados.
- `test_persist_file_contains_valid_json` — o arquivo gravado é JSON válido com `entries`.
- `test_load_returns_same_data` — `load()` recarrega todas as entradas.
- `test_load_returns_empty_when_file_missing` — arquivo ausente retorna banco vazio.
- `test_load_or_create_alias_works` — `load_or_create` funciona como alias de `load`.
- `test_persist_and_reload_roundtrip` — roundtrip preserva valores de todos os tipos.
- `test_persist_preserves_entry_source` — o `source` da entrada sobrevive ao roundtrip.
- `test_version_preserved_on_load` — o campo `version` é preservado na carga.
