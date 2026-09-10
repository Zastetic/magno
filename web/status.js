// Verificação interna: prova que a SPA é servida pela mesma origem da API e que a CSP
// permite este arquivo externo (script-src 'self'). Sem handler inline, sem build.
const status = document.getElementById("status");

function item(rotulo, valor) {
  const li = document.createElement("li");
  const b = document.createElement("strong");
  b.textContent = rotulo + ": ";
  li.appendChild(b);
  li.appendChild(document.createTextNode(valor));
  return li;
}

fetch("/api/saude")
  .then((r) => r.json())
  .then((d) => {
    status.textContent = "";
    status.appendChild(item("Saúde", d.ok ? "OK" : "FALHA"));
    status.appendChild(item("Versão", d.versao));
    status.appendChild(item("Banco", d.banco.arquivo));
    status.appendChild(item(
      "Tabelas",
      d.banco.tabelas + " (" + Object.entries(d.banco.contagens)
        .filter(([, n]) => n > 0).map(([t, n]) => t + "=" + n).join(", ") + ")"
    ));
    status.appendChild(item("Índices", String(d.banco.indices)));
    status.appendChild(item("Integridade", d.banco.integridade));
    status.appendChild(item("Regras", "slot " + d.regras.slot_min + "min · buffer " +
      d.regras.buffer_min + "min · antecedência " + d.regras.antecedencia_min_h + "h · janela " +
      d.regras.janela_dias + " dias · cancelar até " + d.regras.cancelamento_limite_h + "h antes"));
  })
  .catch((e) => {
    status.textContent = "";
    status.appendChild(item("Erro", String(e)));
  });
