import { useState } from "react";
import CitySelect from "./components/CitySelect.jsx";
import RecordPanel from "./components/RecordPanel.jsx";

function App() {
  const [city, setCity] = useState("杭州");

  return (
    <main className="page">
      <h1>语音约碰面地点</h1>
      <p>说出两个人的位置，系统会推荐中间附近的碰面场所。</p>
      <CitySelect value={city} onChange={setCity} />
      <RecordPanel />
    </main>
  );
}

export default App;
