// Prova de que o JavaScript foi servido com o Content-Type correto e executou.
const jsStatus = document.getElementById("js-status");
jsStatus.textContent = "JavaScript carregado e executado.";
jsStatus.className = "ok";

// Uma requisição extra para /data/info.json (reaproveita a conexão persistente).
fetch("/data/info.json")
  .then((response) => response.json())
  .then((data) => {
    const jsonStatus = document.getElementById("json-status");
    jsonStatus.textContent = `JSON carregado: ${data.grupo} - ${data.trabalho}`;
    jsonStatus.className = "ok";
  });
