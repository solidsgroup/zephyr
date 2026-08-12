import { useEffect, useRef, useState } from "react";

interface LazyVideoProps {
  src: string;
  label: string;
  className?: string;
}

export default function LazyVideo({ src, label, className }: LazyVideoProps) {
  const video = useRef<HTMLVideoElement>(null);
  const [nearViewport, setNearViewport] = useState(false);

  useEffect(() => {
    const element = video.current;
    if (!element) return;
    if (!("IntersectionObserver" in window)) {
      setNearViewport(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setNearViewport(true);
        observer.disconnect();
      }
    }, { rootMargin: "120px" });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const play = () => {
    const pending = video.current?.play();
    if (pending) void pending.catch(() => undefined);
  };

  return (
    <video
      ref={video}
      className={className}
      src={nearViewport ? src : undefined}
      aria-label={label}
      muted
      loop
      playsInline
      preload={nearViewport ? "metadata" : "none"}
      onMouseEnter={play}
      onMouseLeave={() => video.current?.pause()}
    />
  );
}
