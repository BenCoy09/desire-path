(function(){var D=document,R=D.documentElement;
function g(k){try{return localStorage.getItem(k)}catch(e){return null}}
function s(k,v){try{localStorage.setItem(k,v)}catch(e){}}
var th=g("theme");if(th&&th!=="auto")R.dataset.theme=th;
var mo=g("motion");if(mo&&mo!=="auto")R.dataset.motion=mo;
window.DP={get:g,set:s,root:R};
if(!g("cookies")){var b=D.createElement("div");b.id="ck";
b.innerHTML='<p>We do not track you. Essential storage keeps your settings. Analytics stay off unless you allow them (none are active yet).</p><button class="btn" data-c="essential">Essential only</button><button class="btn pri" data-c="all">Allow analytics</button>';
b.onclick=function(e){var c=e.target.getAttribute("data-c");if(c){s("cookies",c);b.remove()}};
D.addEventListener("DOMContentLoaded",function(){D.body.appendChild(b)})}
})();
