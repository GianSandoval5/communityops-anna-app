import { AnnaAppRuntime } from "/static/anna-apps/_sdk/latest/index.js";

// Placeholder fallback for local preview
let anna = null;
let TOOL_ID = "tool-communityops-tool-placeholder";

// Load minted Tool ID if injected on publish
if (typeof anna_tool_ids !== "undefined" && anna_tool_ids["communityops-tool"]) {
  TOOL_ID = anna_tool_ids["communityops-tool"];
}

async function init() {
  const statusText = document.getElementById("statusText");
  try {
    statusText.innerText = "Connecting to Anna...";
    anna = await AnnaAppRuntime.connect();
    statusText.innerText = "Connected to Anna";
    
    // Load historical readiness score if any
    const { value: lastScore } = await anna.storage.get({ key: "readiness_score" });
    if (lastScore) {
      document.getElementById("readinessBadge").innerText = `Readiness: ${lastScore}%`;
    }
  } catch (err) {
    console.warn("Anna App SDK not found or running in standalone mode. Using mock mode.", err);
    statusText.innerText = "Mock Mode (Local Preview)";
  }

  setupTabs();
  setupActionButtons();
}

function setupTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      // Remove active from all tabs
      document.querySelectorAll(".tab-btn").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));

      // Add active to selected
      tab.classList.add("active");
      const paneId = `tab-${tab.dataset.tab}`;
      document.getElementById(paneId).classList.add("active");
    });
  });
}

function getParams() {
  return {
    community_type: document.getElementById("communityType").value,
    event_name: document.getElementById("eventName").value,
    details: document.getElementById("eventDetails").value
  };
}

function setupActionButtons() {
  const statusText = document.getElementById("statusText");

  async function callTool(action, outputElementId, extraArgs = {}) {
    const params = getParams();
    const outputEl = document.getElementById(outputElementId);
    outputEl.innerHTML = "<em>Generating with Anna LLM... Please wait.</em>";
    statusText.innerText = `Calling tool: ${action}...`;

    const args = {
      action: action,
      community_type: params.community_type,
      event_name: params.event_name,
      details: params.details,
      ...extraArgs
    };

    if (!anna) {
      // Mock mode fallback
      setTimeout(() => {
        outputEl.innerText = `[MOCK RESULT] Generated ${action} for "${params.event_name}" (${params.community_type}).\n\nDetails: ${params.details || "None"}\n\nThis is a local mock preview. Install the app in Anna to run the real AI pipeline!`;
        statusText.innerText = "Mock action complete";
      }, 1000);
      return;
    }

    try {
      const response = await anna.tools.invoke({
        tool_id: TOOL_ID,
        method: "communityops",
        args: args
      });

      if (response && response.success && response.data) {
        const textResult = response.data.result || response.data;
        outputEl.innerText = textResult;
        statusText.innerText = "Generation complete";

        // If risk assessment, extract readiness score and save to storage
        if (action === "assess_risks" && response.data.score) {
          const score = response.data.score;
          document.getElementById("readinessBadge").innerText = `Readiness: ${score}%`;
          await anna.storage.set({ key: "readiness_score", value: score.toString() });
        }
      } else {
        outputEl.innerText = `Error: ${JSON.stringify(response)}`;
        statusText.innerText = "Tool execution returned invalid response";
      }
    } catch (err) {
      outputEl.innerText = `Error calling tool: ${err.message}`;
      statusText.innerText = "Tool execution failed";
      console.error(err);
    }
  }

  document.getElementById("btnPlan").addEventListener("click", () => {
    callTool("generate_plan", "planOutput");
  });

  document.getElementById("btnChecklist").addEventListener("click", () => {
    callTool("generate_checklist", "checklistOutput");
  });

  document.getElementById("btnSpeakerComms").addEventListener("click", () => {
    callTool("draft_comms", "commsOutput", { comms_type: "speaker" });
  });

  document.getElementById("btnSponsorComms").addEventListener("click", () => {
    callTool("draft_comms", "commsOutput", { comms_type: "sponsor" });
  });

  document.getElementById("btnRisks").addEventListener("click", () => {
    callTool("assess_risks", "risksOutput");
  });
}

document.addEventListener("DOMContentLoaded", init);
