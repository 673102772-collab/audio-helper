import { STAGE_LABELS } from "../useMeetupRun.js";

function formatMeters(value) {
  const meters = Number(value);
  if (!Number.isFinite(meters)) {
    return null;
  }
  return `${Math.round(meters)}`;
}

export default function ResultPanel({
  stage,
  error,
  results,
  audioRef,
  onPlayManually,
}) {
  const statusText = stage === "error" ? "处理失败" : STAGE_LABELS[stage] || "";
  const showStatus = Boolean(statusText) && stage !== "idle";

  return (
    <section className="result-panel">
      {showStatus ? (
        <p className={stage === "error" ? "pipeline-status error" : "pipeline-status"} role="status">
          {statusText}
        </p>
      ) : null}

      {error ? (
        <p className="error-detail">
          {error.message}
          {error.code || error.stage
            ? `（${[error.code, error.stage].filter(Boolean).join(" / ")}）`
            : ""}
        </p>
      ) : null}

      {results.asrText ? (
        <article className="result-card">
          <h2>识别文字</h2>
          <p>{results.asrText}</p>
        </article>
      ) : null}

      {results.extract ? (
        <article className="result-card">
          <h2>提取信息</h2>
          <dl className="extract-list">
            <div>
              <dt>地点 A</dt>
              <dd>
                {results.extract.city_a} {results.extract.address_a}
              </dd>
            </div>
            <div>
              <dt>地点 B</dt>
              <dd>
                {results.extract.city_b} {results.extract.address_b}
              </dd>
            </div>
            <div>
              <dt>类型</dt>
              <dd>{results.extract.category}</dd>
            </div>
          </dl>
        </article>
      ) : null}

      {results.pois.length > 0 ? (
        <article className="result-card">
          <h2>候选店铺</h2>
          <ol className="poi-list">
            {results.pois.map((poi, index) => {
              const meters = formatMeters(poi.distance_to_midpoint_m);
              return (
                <li key={`${poi.name}-${poi.address}-${index}`}>
                  <strong>{poi.name}</strong>
                  <p>{poi.address}</p>
                  {meters !== null ? <p className="note">距离中点 {meters} 米</p> : null}
                </li>
              );
            })}
          </ol>
        </article>
      ) : null}

      {results.replyText ? (
        <article className="result-card">
          <h2>推荐语</h2>
          <p>{results.replyText}</p>
          {results.warning ? <p className="warning">{results.warning}</p> : null}
          {results.ttsUrl ? (
            <audio ref={audioRef} controls src={results.ttsUrl} preload="auto">
              浏览器无法播放这段语音
            </audio>
          ) : null}
          {results.needsManualPlay ? (
            <button type="button" className="play-button" onClick={onPlayManually}>
              点击播放
            </button>
          ) : null}
        </article>
      ) : null}
    </section>
  );
}
