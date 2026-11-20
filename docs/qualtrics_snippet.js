/* Paste into the JavaScript editor of a Text/Graphic question in Qualtrics.
 *
 * Before fielding, create these embedded data fields in the Survey Flow (above the question):
 *   map_arm, map_set, map_data, map_code
 * To have Qualtrics assign the treatment, set an embedded field `arm` with a Randomizer and it is
 * passed through below; leave it empty and the map assigns an arm from the response ID.
 * Results arrive as JSON in map_data: one object per option per task.
 */
Qualtrics.SurveyEngine.addOnload(function () {
  var BASE = "https://lobsterbush.github.io/isometric-melbourne/";
  var STUDY = "neighbourhood-choice";            // name of the file in docs/studies/
  var q = this;
  q.hideNextButton();

  var params = "study=" + STUDY + "&mode=survey&pid=" + encodeURIComponent("${e://Field/ResponseID}");
  var arm = "${e://Field/arm}";
  if (arm) params += "&arm=" + encodeURIComponent(arm);

  var frame = document.createElement("iframe");
  frame.src = BASE + "experiment.html?" + params;
  frame.title = "Map task";
  frame.style.cssText = "width:100%;height:900px;border:0;";
  q.getQuestionTextContainer().appendChild(frame);

  window.addEventListener("message", function (ev) {
    if (ev.origin !== "https://lobsterbush.github.io") return;
    var d = ev.data;
    if (!d || d.source !== "isometric-melbourne" || d.type !== "complete") return;
    Qualtrics.SurveyEngine.setEmbeddedData("map_arm", d.arm);
    Qualtrics.SurveyEngine.setEmbeddedData("map_set", d.choiceSet);
    Qualtrics.SurveyEngine.setEmbeddedData("map_code", d.code);
    Qualtrics.SurveyEngine.setEmbeddedData("map_data", JSON.stringify(d.rows));
    q.showNextButton();
    q.clickNextButton();
  });
});
