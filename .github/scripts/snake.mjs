// Snake animasyonunu generate-snake-animation CLI'ı ile üretir.
// 2026 boyunca takvimi 1 Ocak 2026'dan bugüne kısıtlar (boş 2025 sonu görünmesin).
// 2027'den itibaren hiçbir şeye dokunmaz; GitHub'ın varsayılanı olan "son 1 yıl" kullanılır.
const YEAR_ONLY_UNTIL = 2026;

const year = new Date().getUTCFullYear();
if (year <= YEAR_ONLY_UNTIL) {
  const from = `${year}-01-01T00:00:00Z`;
  const to = new Date().toISOString();
  const realFetch = globalThis.fetch;
  globalThis.fetch = (url, init) => {
    if (String(url).endsWith("/graphql") && init?.body) {
      const body = JSON.parse(init.body);
      body.query = body.query
        .replace("query ($login: String!)", "query ($login: String!, $from: DateTime!, $to: DateTime!)")
        .replace("contributionsCollection {", "contributionsCollection(from: $from, to: $to) {");
      if (!body.query.includes("$from, to: $to")) throw new Error("snake: GraphQL query format changed");
      body.variables = { ...body.variables, from, to };
      init = { ...init, body: JSON.stringify(body) };
      console.log(`📅 limiting calendar to ${from} → ${to}`);
    }
    return realFetch(url, init);
  };
}

await import("generate-snake-animation/cli.js");
