import { useEffect, useRef, useState } from 'react'
import { Eye, EyeOff, LockKeyhole, ShieldCheck, UserRound } from 'lucide-react'
import './login.css'
import './effects.css'
import './cinematic-motion.css'

type Props={username:string;password:string;error:string;pending:boolean;onUsernameChange:(v:string)=>void;onPasswordChange:(v:string)=>void;onSubmit:(e:React.FormEvent)=>void}

export function LoginPage(props:Props){
  const shell=useRef<HTMLElement>(null);const frame=useRef<number|null>(null)
  const move=(e:React.PointerEvent<HTMLElement>)=>{if(e.pointerType==='touch'||!shell.current)return;if(frame.current)cancelAnimationFrame(frame.current);const x=e.clientX/window.innerWidth-.5,y=e.clientY/window.innerHeight-.5;frame.current=requestAnimationFrame(()=>{const s=shell.current?.style;if(!s)return;s.setProperty('--scene-x',`${(-x*14).toFixed(1)}px`);s.setProperty('--scene-y',`${(-y*9).toFixed(1)}px`);s.setProperty('--lion-x',`${(-x*34).toFixed(1)}px`);s.setProperty('--lion-y',`${(-y*22).toFixed(1)}px`);s.setProperty('--map-x',`${(-x*17).toFixed(1)}px`);s.setProperty('--map-y',`${(-y*11).toFixed(1)}px`);s.setProperty('--truck-x',`${(-x*25).toFixed(1)}px`);s.setProperty('--truck-y',`${(-y*15).toFixed(1)}px`)})}
  return <main ref={shell} className="cinematic-login" onPointerMove={move}><LoginCinematicScene/><LoginPanel {...props}/></main>
}

function LoginCinematicScene(){return <section className="login-scene" aria-label="Seven Cargo — inteligência logística em movimento"><div className="login-scene__image"/><div className="login-scene__depth login-scene__lion"/><div className="login-scene__depth login-scene__map"/><div className="login-scene__depth login-scene__truck"/><div className="login-scene__headlights"/><div className="login-scene__spray"/><div className="login-scene__road"/><RainLayer/><div className="login-scene__brand"><img src="/login/seven-cargo-logo.png" alt="Seven Cargo"/><div><h1>Controle<br/><strong>Operacional</strong></h1><p>Inteligência em movimento.<br/>Excelência em cada entrega.</p></div></div></section>}
function RainLayer(){
  const canvas=useRef<HTMLCanvasElement>(null)
  useEffect(()=>{const node=canvas.current;if(!node)return;const context=node.getContext('2d');if(!context)return;let width=0,height=0,frame=0,last=performance.now(),drops:Drop[]=[];const reduced=matchMedia('(prefers-reduced-motion: reduce)');
    const seed=(depth:number):Drop=>({x:Math.random()*width,y:Math.random()*height,depth,length:3+Math.random()*7+depth*6,speed:95+Math.random()*110+depth*205,wind:18+Math.random()*18,width:.55+depth*.72,alpha:.15+Math.random()*.16+depth*.07})
    const resize=()=>{const rect=node.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,1.75);width=rect.width;height=rect.height;node.width=Math.round(width*dpr);node.height=Math.round(height*dpr);context.setTransform(dpr,0,0,dpr,0,0);const factor=width<760?.3:width<1200?.68:1;const count=Math.round(Math.min(185,width*.13)*factor);drops=Array.from({length:count},(_,i)=>seed(i<count*.5?0:i<count*.86?1:2))}
    const draw=(now:number)=>{frame=requestAnimationFrame(draw);if(document.hidden||reduced.matches)return;const dt=Math.min((now-last)/1000,.034);last=now;context.clearRect(0,0,width,height);for(const drop of drops){drop.x+=drop.wind*dt;drop.y+=drop.speed*dt;if(drop.y>height+30||drop.x>width+30){Object.assign(drop,seed(drop.depth),{x:Math.random()*width-50,y:-30-Math.random()*height*.2})}context.beginPath();context.moveTo(drop.x,drop.y);context.lineTo(drop.x+drop.wind*.055,drop.y+drop.length);context.lineWidth=drop.width;context.strokeStyle=`rgba(220,232,240,${drop.alpha})`;context.shadowBlur=drop.depth===2?2.5:0;context.shadowColor='rgba(220,232,240,.22)';context.stroke()}context.shadowBlur=0;const mist=context.createLinearGradient(0,height*.72,0,height);mist.addColorStop(0,'rgba(220,225,215,0)');mist.addColorStop(.75,'rgba(225,205,155,.035)');mist.addColorStop(1,'rgba(235,215,175,.08)');context.fillStyle=mist;context.fillRect(0,height*.72,width,height*.28)}
    const visible=()=>{last=performance.now()};resize();addEventListener('resize',resize);document.addEventListener('visibilitychange',visible);frame=requestAnimationFrame(draw);return()=>{cancelAnimationFrame(frame);removeEventListener('resize',resize);document.removeEventListener('visibilitychange',visible)}
  },[])
  return <canvas ref={canvas} className="login-rain-canvas" aria-hidden="true"/>
}

type Drop={x:number;y:number;depth:number;length:number;speed:number;wind:number;width:number;alpha:number}

function LoginPanel({username,password,error,pending,onUsernameChange,onPasswordChange,onSubmit}:Props){
  const [visible,setVisible]=useState(false)
  return <section className="login-panel-wrap"><form className="login-panel" onSubmit={onSubmit}>
    <span className="login-panel__eyebrow">Central de operações</span><h2>Bem-vindo ao<br/><strong>Painel Seven Cargo</strong></h2><p className="login-panel__intro">Acesse o ambiente operacional seguro.</p>
    <label className="login-field"><span className="sr-only">Usuário</span><UserRound size={19}/><input aria-label="Usuário" placeholder="Usuário" autoComplete="username" value={username} onChange={e=>onUsernameChange(e.target.value)} required maxLength={100}/></label>
    <label className="login-field"><span className="sr-only">Senha</span><LockKeyhole size={19}/><input aria-label="Senha" placeholder="Senha" type={visible?'text':'password'} autoComplete="current-password" value={password} onChange={e=>onPasswordChange(e.target.value)} required maxLength={500}/><button className="login-field__reveal" type="button" onClick={()=>setVisible(v=>!v)} aria-label={visible?'Ocultar senha':'Mostrar senha'} aria-pressed={visible}>{visible?<EyeOff size={19}/>:<Eye size={19}/>}</button></label>
    {error&&<div className="login-panel__error" role="alert">{error}</div>}<button className="login-panel__submit" type="submit" disabled={pending}>{pending?'Entrando...':'Entrar'}</button><footer><ShieldCheck size={15}/>Sistema protegido e monitorado 24/7</footer>
  </form></section>
}
