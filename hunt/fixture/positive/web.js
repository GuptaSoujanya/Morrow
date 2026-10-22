// Planted positive fixture for the JavaScript semgrep packs.
function render(input) {
  document.getElementById("out").innerHTML = input;
  eval(input);
  document.write(location.hash);
}
