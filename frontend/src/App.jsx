import { useState } from "react";
import CitySelect from "./components/CitySelect.jsx";
import RecordPanel from "./components/RecordPanel.jsx";
import ResultPanel from "./components/ResultPanel.jsx";
import { useMeetupRun } from "./useMeetupRun.js";

function App() {
  const [city, setCity] = useState("杭州");
  const run = useMeetupRun();

  return (
    <main className="page">
      <h1>语音约碰面地点</h1>
      <p>说出两个人的位置，系统会推荐中间附近的碰面场所。</p>
      <p className={run.health === "ok" ? "health ok" : "health warn"} role="status">
        {run.healthMessage}
      </p>
      <CitySelect value={city} onChange={setCity} disabled={run.busy} />
      <RecordPanel
        busy={run.busy}
        onRoundStart={run.clearRound}
        onClipReady={(clip) => run.start(clip, city)}
      />
      <ResultPanel
        stage={run.stage}
        error={run.error}
        results={run.results}
        audioRef={run.audioRef}
        onPlayManually={run.playManually}
      />
    </main>
  );
}

export default App;
