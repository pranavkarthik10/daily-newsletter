(function(){
  var KEY='mt.collapsed', collapsed={};
  try{collapsed=JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}
  document.querySelectorAll('.sec').forEach(function(s){
    var id=s.dataset.id, b=s.querySelector('.fold'), m=s.querySelector('.more');
    if(collapsed[id]){s.classList.add('collapsed');b.textContent='+'}
    b.addEventListener('click',function(){
      var c=s.classList.toggle('collapsed'); b.textContent=c?'+':'−';
      if(c)collapsed[id]=1; else delete collapsed[id];
      try{localStorage.setItem(KEY,JSON.stringify(collapsed))}catch(e){}
    });
    if(m){var n=m.dataset.n;m.addEventListener('click',function(){
      var o=s.classList.toggle('open'); m.textContent=o?'Show fewer':n+' more';
      if(!o)s.scrollIntoView({block:'nearest'});
    })}
  });
  function rel(ts){var m=(Date.now()-ts)/6e4;if(m<1)return'just now';if(m<60)return Math.floor(m)+'m ago';if(m<1440)return Math.floor(m/60)+'h ago';return Math.floor(m/1440)+'d ago'}
  function tick(){
    document.querySelectorAll('[data-ts]').forEach(function(el){el.textContent=rel(+el.dataset.ts)});
    var now=Date.now();
    document.querySelectorAll('.ev[data-end]').forEach(function(el){
      el.classList.toggle('past',now>+el.dataset.end);
      el.classList.toggle('now',now>=+el.dataset.start&&now<=+el.dataset.end);
    });
  }
  tick(); setInterval(tick,60000);
  var q=document.querySelector('.search input');
  document.addEventListener('keydown',function(e){
    if(e.key==='/'&&document.activeElement!==q&&!/input|textarea/i.test(document.activeElement.tagName)){e.preventDefault();q.focus()}
    if(e.key==='Escape'&&document.activeElement===q)q.blur();
  });
})();
