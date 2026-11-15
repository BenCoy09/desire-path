(function(){var D=document,R=D.documentElement;
function g(k){try{return localStorage.getItem(k)}catch(e){return null}}
function s(k,v){try{localStorage.setItem(k,v)}catch(e){}}
var th=g("theme");if(th&&th!=="auto")R.dataset.theme=th;
var mo=g("motion");if(mo&&mo!=="auto")R.dataset.motion=mo;
window.DP={get:g,set:s,root:R};
DP.me=new Promise(function(res){try{fetch("/me").then(function(r){return r.json().then(function(d){res(r.status===200&&d&&d.email?d:null)},function(){res(null)})},function(){res(null)})}catch(e){res(null)}});
function esc(x){return String(x).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]})}
var LOGO='<svg class="logo" viewBox="0 0 32 32"><path d="M5 27C9 20 12 23 16 16S22 8 27 5" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-dasharray="4 4"/></svg>';
DP.navHTML=function(me,path){
var h='<a class="brand" href="/">'+LOGO+'Desire Path</a><a href="/#how">How it works</a><a href="/#proof">Proof</a><a href="/#pricing">Pricing</a><a href="/#faq">FAQ</a><a href="/docs">Docs</a>';
if(me){var dm=/@demo\.invalid$/.test(me.email);
h+='<span class="avatar" title="'+esc(dm?"Demo workspace":me.email)+'">'+esc(dm?"D":me.email.charAt(0).toUpperCase())+'</span><button class="btn" id="dp-out">Log out</button>';
if(path!=="/app")h+='<a class="btn pri" href="/app">Workspace</a>'}
else{h+='<a href="/account#login">Sign in</a>';if(path!=="/app")h+='<a class="btn pri" href="/app">Try the demo</a>'}
return h};
function nav(me){var w=D.querySelector("nav .wrap");if(!w)return;
var p=window.DP_PATH||(location.pathname.replace(/\/+$/,"")||"/");w.innerHTML=DP.navHTML(me,p);
var o=D.getElementById("dp-out");
if(o)o.onclick=function(){fetch("/auth/logout",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"}).then(function(){location="/"},function(){location="/"})}}
D.addEventListener("DOMContentLoaded",function(){nav(null);DP.me.then(function(me){if(me)nav(me)})});
if(!g("cookies")){var b=D.createElement("div");b.id="ck";
b.innerHTML='<p>We do not track you. Essential storage keeps your settings. Analytics stay off unless you allow them (none are active yet).</p><button class="btn" data-c="essential">Essential only</button><button class="btn pri" data-c="all">Allow analytics</button>';
b.onclick=function(e){var c=e.target.getAttribute("data-c");if(c){s("cookies",c);b.remove()}};
D.addEventListener("DOMContentLoaded",function(){D.body.appendChild(b)})}
})();
