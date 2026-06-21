import {makeProject} from "@revideo/core";
import scene from "./scene?scene";

export default makeProject({
  scenes: [scene],
  variables: {
    renderPlan: "{}",
    sourceVideo: "",
  },
});
