const { chromium } = require("playwright-core");
const fs = require("fs");
const P = "/home/user/Liliia-/montage/FableCut/project.json";
const OUT = "/home/user/Liliia-/montage/projects/test/";
(async () => {
  const b = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" });
  const pg = await b.newPage({ viewport: { width: 1600, height: 1000 } });
  await pg.goto("http://localhost:7777", { waitUntil: "networkidle" });
  await pg.waitForTimeout(2500);
  await pg.screenshot({ path: OUT + "07_fablecut_do_pravki.png" });
  const before = await pg.evaluate(() => document.body.innerText.includes("Титр из FableCut"));
  // правка в project.json на диске, как её делает агент
  const d = JSON.parse(fs.readFileSync(P, "utf8"));
  d.clips.find(c => c.id === "c_t").props.text = "Правка из project.json";
  d.clips.find(c => c.id === "c_t").props.color = "#e8b04a";
  d.revision += 1;
  fs.writeFileSync(P, JSON.stringify(d, null, 2));
  await pg.waitForTimeout(1500);
  await pg.screenshot({ path: OUT + "07_fablecut_posle_pravki.png" });
  const title = await pg.title();
  console.log("title:", title, "| revision on disk:", d.revision);
  await b.close();
})();
