"use strict";

let mouse_pos;
let widthDefault;
const borderWidth = 30; // drag click area is actually dependent on the pseudo element width. this is arbitrary high value
const wordFrame = document.getElementById("wordframeid");

applyInitialPaneSizes();

function resizeCol(e){
  const dx = mouse_pos - e.x;
  mouse_pos = e.x;
  // getting the width with computedStyle doesn't seem to be working correctly.
  // getting width directly, but for this initial width must be set via javascript 
  // so the style is inline for this code to work
  const currentWidthLeft = readPaneLeft.style.width;
  const readPaneWidth = parseFloat(window.getComputedStyle(readPaneContainer).getPropertyValue("width"));
  // const currentWidthLeft = parseFloat(window.getComputedStyle(readPaneLeft).getPropertyValue("width"));

  let lfWidthPct = parseFloat(currentWidthLeft) - (dx / readPaneWidth * 100);
  lfWidthPct = clamp(lfWidthPct, 25, 95);
  const rtWidthPct = (100 - lfWidthPct) * getReadPaneWidthRatio();

  readPaneLeft.style.width = `${lfWidthPct}%`;
  readPaneRight.style.width = `${rtWidthPct}%`;

  localStorage.setItem("textWidth", lfWidthPct);
}

readPaneRight.addEventListener("mousedown", function(e){
  if (e.offsetX < borderWidth) {
    setIFrameStatus("none");
    mouse_pos = e.x;
    document.addEventListener("mousemove", resizeCol);
    e.preventDefault(); // prevent selection
  }
});

// double click -> widen to 95% temporarily (doesn't save state)
readPaneRight.addEventListener("dblclick", function(e){
  if (e.target != e.currentTarget) return; // fixes: clicking dict tabs resizes panes
  
  if (e.offsetX < borderWidth) {
    // if the width is 95% then return to the last width value
    if (readPaneLeft.style.width == "95%") {
      const width = getFromLocalStorage("textWidth", widthDefault);
      readPaneLeft.style.width = `${width}%`;
      readPaneRight.style.width = `${(100 - width) * getReadPaneWidthRatio()}%`;
    } else {
      readPaneLeft.style.width = "95%";
      readPaneRight.style.width = `${5 * getReadPaneWidthRatio()}%`;
    }
    }
});

document.addEventListener("pointerup", function(){
  document.removeEventListener("mousemove", resizeCol);
  setIFrameStatus("unset");
});

// if the iframes are clickable mousemove doesn't work correctly
function setIFrameStatus(status) {
  wordFrame.style.pointerEvents = status;
}

// because right side is fixed. it's width value is different. need to find ratio
// basically: when gridContainer width is 100%, this doesn't mean that it takes the whole 
// viewport width. it can be less than that. but for the right side it's an absolute percentage value
function getReadPaneWidthRatio() {
  return parseFloat(window.getComputedStyle(readPaneContainer).getPropertyValue("width")) / parseFloat(document.documentElement.clientWidth);
}

function clamp (num, min, max) {
  return Math.min(Math.max(num, min), max);
}

function getTextWidthPercentage() {
  // returns percentage value
  const elementComputedStyle = window.getComputedStyle(readPaneLeft);
  return (parseFloat(elementComputedStyle.getPropertyValue("width")) / parseFloat(window.getComputedStyle(readPaneContainer).getPropertyValue("width"))) * 100;
  // return parseFloat(elementComputedStyle.width);
}

function applyInitialPaneSizes() {
  widthDefault = getTextWidthPercentage();

  const width = getFromLocalStorage("textWidth", widthDefault);
  const ratio = getReadPaneWidthRatio();
  const pane_right_width = (100 - width) * ratio;

  readPaneLeft.style.width = `${width}%`;
  readPaneRight.style.width = `${pane_right_width}%`;
}

function getFromLocalStorage(item, defaultVal) {
  // return Number(localStorage.getItem(item) ?? defaultVal);
  const storageVal = localStorage.getItem(item);
  
  if ((!storageVal) || isNaN(storageVal)) {
    return Number(defaultVal);
  } else {
    return Number(storageVal);
  }
}
